"""Makes up a year of households, devices, IP changes and ad/site events.

Everything here is invented. Two things come out:

  * the EVENT LOG   - what a CTV platform plus an advertiser's site pixel
                      would actually see (IP, TV ad ID, cookie, hashed email)
  * the ANSWER KEY  - which household every event really belongs to, and
                      which IP every household really had on every day

The resolver only ever gets the event log. The answer key is used afterwards
to score it.

IP addresses are drawn from ranges reserved for testing and carrier NAT, so
they cannot collide with anyone's real address:
  198.18.0.0/15   home broadband
  100.64.0.0/10   mobile carriers (many customers behind one address)
  192.0.2.0/24    offices and public Wi-Fi
"""
import hashlib
import math
import random
from bisect import bisect_right

from .settings import DAY

IP_TYPE_PREFIXES = [
    ("198.18.", "residential"),
    ("198.19.", "residential"),
    ("100.", "cellular"),
    ("192.0.2.", "business"),
]


def ip_type(ip):
    """Stands in for a commercial IP-type lookup (home / mobile / business)."""
    for prefix, kind in IP_TYPE_PREFIXES:
        if ip.startswith(prefix):
            return kind
    return "unknown"


class Rng:
    """Small wrapper so results are identical on every Python version."""

    def __init__(self, seed):
        self._r = random.Random(int(seed))

    def u(self):
        return self._r.random()

    def chance(self, p):
        return self._r.random() < p

    def pick(self, seq):
        return seq[int(self._r.random() * len(seq))]

    def weighted(self, pairs):
        total = sum(w for _, w in pairs)
        x = self._r.random() * total
        for value, w in pairs:
            x -= w
            if x < 0:
                return value
        return pairs[-1][0]

    def expo(self, mean):
        return -math.log(1.0 - self._r.random()) * mean

    def poisson(self, lam):
        limit = math.exp(-lam)
        k, p = 0, 1.0
        while True:
            p *= self._r.random()
            if p <= limit:
                return k
            k += 1

    def between(self, a, b):
        return a + int(self._r.random() * (b - a + 1))

    def hexid(self, n):
        return "".join("0123456789abcdef"[int(self._r.random() * 16)] for _ in range(n))


class Simulation:
    """Holds the event log and the answer key."""

    def __init__(self):
        self.events = []        # observable rows (dicts)
        self.truth = {}         # event_id -> (true household id, place)
        self.households = []    # answer-key household records
        self.cookie_owner = {}  # cookie_id -> true household id
        self.email_owner = {}   # hashed email -> true household id
        self.tv_owner = {}      # ctv_id -> true household id
        self.total_seconds = 0

    def home_ip(self, hh, ts):
        """The IP a household really had at a moment in time."""
        starts = hh["_lease_starts"]
        i = bisect_right(starts, ts) - 1
        return hh["leases"][max(i, 0)][2]


def _unique_ips(rng, count, make):
    seen, out = set(), []
    while len(out) < count:
        ip = make(rng)
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def simulate(cfg):
    rng = Rng(cfg["seed"])
    n_homes = int(cfg["households"])
    days = int(cfg["days"])
    total = days * DAY
    sim = Simulation()
    sim.total_seconds = total

    # ---------------------------------------------------------------- places
    ipc = cfg["ip_changes"]
    spare = max(5, int(n_homes * ipc["spare_addresses_per_100_homes"] / 100.0))
    home_pool = _unique_ips(
        rng, n_homes + spare,
        lambda r: "198.%d.%d.%d" % (r.between(18, 19), r.between(0, 255), r.between(1, 254)))
    carrier_ips = _unique_ips(
        rng, 12,
        lambda r: "100.%d.%d.%d" % (r.between(64, 127), r.between(0, 255), r.between(1, 254)))
    n_work = min(200, max(10, n_homes // 15))
    n_public = 12
    shared = _unique_ips(rng, n_work + n_public, lambda r: "192.0.2.%d" % r.between(1, 254))
    work_ips, public_ips = shared[:n_work], shared[n_work:]

    # ------------------------------------------------------------ households
    tvc = cfg["tv"]
    site = cfg["site"]
    camp = cfg["campaign"]
    person_no = 0
    for i in range(n_homes):
        hid = "H%04d" % (i + 1)
        lease_class = rng.weighted([
            ("stable", ipc["stable_share"]),
            ("typical", ipc["typical_share"]),
            ("frequent", ipc["frequent_share"]),
        ])
        tv_class = rng.weighted([
            ("heavy", tvc["heavy_share"]),
            ("regular", tvc["regular_share"]),
            ("light", tvc["light_share"]),
            ("rare", tvc["rare_share"]),
        ])
        people = []
        for _ in range(rng.weighted([(1, 0.25), (2, 0.35), (3, 0.20), (4, 0.20)])):
            person_no += 1
            email = hashlib.sha256(("person%d@example.com" % person_no).encode()).hexdigest()
            sim.email_owner[email] = hid
            people.append({
                "email": email,
                "has_laptop": rng.chance(site["laptop_ownership"]),
                "work_ip": rng.pick(work_ips) if rng.chance(0.7) else None,
                "cookies": {},  # device -> (cookie_id, expires_ts)
            })
        sim.households.append({
            "id": hid,
            "lease_class": lease_class,
            "lease_avg_days": ipc[lease_class + "_avg_days"],
            "tv_class": tv_class,
            "tv_chance": tvc[tv_class + "_chance_per_day"],
            "tv_platform": rng.pick(["Roku", "Fire TV", "Samsung", "LG", "Google TV"]),
            "targeted": rng.chance(camp["share_of_households_targeted"]),
            "people": people,
            "friends": [],
            "leases": [],      # (start_ts, end_ts, ip)
            "tv_ids": [],      # (from_ts, ctv_id)
        })
    for i, hh in enumerate(sim.households):
        while len(hh["friends"]) < 2 and n_homes > 2:
            j = rng.between(0, n_homes - 1)
            if j != i and j not in hh["friends"]:
                hh["friends"].append(j)

    # ------------------------------------------------- IP leases (the churn)
    # Homes share one pool. When a home's lease ends its address goes back in
    # and can be handed to a different home - that is the "reassigned to a
    # neighbour" case that fools raw-IP matching.
    speed = max(float(ipc["speed"]), 1e-6)
    changes = []
    for i, hh in enumerate(sim.households):
        t = 0.0
        while True:
            t += max(DAY, rng.expo(hh["lease_avg_days"]) * DAY) / speed
            if t >= total:
                break
            changes.append((t, i))
    changes.sort()
    free = home_pool[n_homes:]
    cooling = []  # (available_ts, ip)
    current = {}
    lease_start = {}
    for i in range(n_homes):
        current[i] = home_pool[i]
        lease_start[i] = 0
    for t, i in changes:
        ts = int(t)
        ready = [c for c in cooling if c[0] <= ts]
        if ready:
            cooling = [c for c in cooling if c[0] > ts]
            free.extend(ip for _, ip in ready)
        if not free:
            continue  # nothing spare right now; this home keeps its address
        new_ip = free.pop(int(rng.u() * len(free)))
        hh = sim.households[i]
        hh["leases"].append((lease_start[i], ts, current[i]))
        cooling.append((ts + DAY, current[i]))
        current[i] = new_ip
        lease_start[i] = ts
    for i, hh in enumerate(sim.households):
        hh["leases"].append((lease_start[i], total, current[i]))
        hh["_lease_starts"] = [l[0] for l in hh["leases"]]

    raw = []  # (ts, type, ip, ctv, cookie, email, true_hid, place)

    # ------------------------------------------------------------- TV events
    reset_per_day = tvc["ad_id_resets_per_year"] / 365.0
    c_start = int(camp["start_day"])
    c_end = c_start + int(camp["length_days"])
    for hh in sim.households:
        ctv = "ctv-" + rng.hexid(8)
        hh["tv_ids"].append((0, ctv))
        sim.tv_owner[ctv] = hh["id"]
        for d in range(days):
            if d > 0 and rng.chance(reset_per_day):
                ctv = "ctv-" + rng.hexid(8)
                hh["tv_ids"].append((d * DAY, ctv))
                sim.tv_owner[ctv] = hh["id"]
            if not rng.chance(hh["tv_chance"]):
                continue
            hour = rng.between(18, 22) if rng.chance(0.7) else rng.between(7, 23)
            ts = d * DAY + hour * 3600 + rng.between(0, 3599)
            kind = "tv_ad_request"
            if hh["targeted"] and c_start <= d < c_end and rng.chance(camp["impression_chance_per_tv_day"]):
                kind = "impression"
            if kind == "tv_ad_request" and not tvc["ad_requests_visible_all_year"]:
                continue  # advertiser-only view: the TV is seen only when it is served an ad
            raw.append((ts, kind, sim.home_ip(hh, ts), ctv, "", "", hh["id"], "home"))

    # ----------------------------------------------------------- site events
    where = cfg["where_people_browse"]
    for hh in sim.households:
        # A "shopping episode" is a burst of visits around one need: a few
        # visits over up to ten days, sometimes ending in a form submission.
        visits = []
        for _ in range(rng.poisson(site["shopping_episodes_per_year"])):
            start_day = rng.between(0, days - 1)
            n_visits = min(6, 1 + rng.poisson(site["extra_visits_per_episode"]))
            offsets = sorted([0] + [rng.between(0, 10) for _ in range(n_visits - 1)])
            lead = rng.pick(hh["people"])
            converts = rng.chance(site["conversion_chance_per_episode"])
            for k, off in enumerate(offsets):
                d = start_day + off
                person = lead if rng.chance(0.75) else rng.pick(hh["people"])
                device = "laptop" if (person["has_laptop"] and rng.chance(site["laptop_use_share"])) else "phone"
                place = rng.weighted(sorted(where[device].items()))
                ts = d * DAY + rng.between(7, 23) * 3600 + rng.between(0, 3599)
                is_conv = converts and k == len(offsets) - 1
                with_email = is_conv or rng.chance(site["email_chance_on_ordinary_visit"])
                if d < days:
                    visits.append((ts, len(visits), person, device, place, is_conv, with_email))
        visits.sort(key=lambda v: (v[0], v[1]))
        for ts, _, person, device, place, is_conv, with_email in visits:
            if place == "work" and not person["work_ip"]:
                place = "home"
            if place == "home":
                ip = sim.home_ip(hh, ts)
            elif place == "cellular":
                ip = rng.pick(carrier_ips)
            elif place == "work":
                ip = person["work_ip"]
            elif place == "public":
                ip = rng.pick(public_ips)
            else:  # at a friend's house, on their Wi-Fi
                ip = sim.home_ip(sim.households[rng.pick(hh["friends"])], ts)
            # Cookies are per browser and get cleared or expire.
            cookie = person["cookies"].get(device)
            if cookie is None or ts > cookie[1]:
                cookie = ("ck-" + rng.hexid(10), ts + rng.expo(site["cookie_avg_life_days"]) * DAY)
                person["cookies"][device] = cookie
                sim.cookie_owner[cookie[0]] = hh["id"]
            raw.append((ts, "conversion" if is_conv else "site_visit", ip, "", cookie[0],
                        person["email"] if with_email else "", hh["id"], place))

    # ------------------------------------------------------- finish the logs
    raw.sort(key=lambda r: (r[0], r[1], r[3], r[4]))
    for n, r in enumerate(raw):
        eid = "E%06d" % (n + 1)
        sim.events.append({
            "event_id": eid, "ts": r[0], "event_type": r[1], "ip": r[2],
            "ctv_id": r[3], "cookie_id": r[4], "hashed_email": r[5],
        })
        sim.truth[eid] = (r[6], r[7])
    return sim
