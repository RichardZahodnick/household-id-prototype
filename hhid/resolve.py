"""The household ID resolver.

Reads the event log in time order and builds a small identity graph:

  * a HOUSEHOLD ID is the stable thing we report on
  * every IP is a date-ranged pointer to a household, never the household itself
  * a new IP is not derived from the old one - it is recognized when something
    already tied to the household (its TV, a known browser, an email) is seen on it

This module never sees the answer key. It gets events (IP, TV ad ID, cookie,
hashed email, timestamp) and an IP-type lookup (home / mobile / business),
and nothing else.

The rules, in plain words:

  R1  A TV anchors a household.         New TV ad ID -> new household at that IP.   [high]
  R2  A known TV on a new IP moves it.  Close the old IP range, open a new one.     [high]
  R3  Browsers join the home they are   1 day on a household's home IP = probable,  [probable /
      seen in.                          2+ separate days = confirmed.                confirmed]
  R4  An email ties browsers together.  Same hashed email on two cookies = same     [high]
                                        person, so they share one household.
  R5  Known browsers can reveal a new   A household's confirmed browser seen on an  [medium]
      IP.                               unclaimed home IP on 2 separate days moves
                                        the household there. The TV overrules it.
  R6  Shared networks are ignored.      Mobile, office and public Wi-Fi IPs are     [guard]
                                        never used to link anything.
  R7  Stale addresses are not trusted.  If nobody has re-confirmed an IP lately,    [guard /
                                        sightings there are held until someone does. weak]
                                        If nobody ever does, they count only as a
                                        weak link to the last household known there.
  R8  New TV ID, same home.             A new TV ID takes over a household's IP,    [medium]
                                        the old TV ID goes silent, and that
                                        household's browsers keep showing up
                                        there -> merge the two.
"""
from .settings import DAY

RULES = [
    ("R1", "A TV anchors a household",
     "The first time a TV ad ID is seen, it starts a new household at that IP. TVs do not leave the house.",
     "High"),
    ("R2", "A known TV on a new IP moves the household",
     "The old IP range is closed and a new one opened. If that IP pointed at another household, that pointer is retired.",
     "High"),
    ("R3", "Browsers join the home they are seen in",
     "A cookie seen on a household's home IP is linked to it: one day is probable, two or more separate days is confirmed.",
     "Probable / confirmed"),
    ("R4", "An email ties browsers together",
     "The same hashed email on two cookies means the same person, so both cookies share one household. This survives cookie clearing and IP changes.",
     "High"),
    ("R5", "Known browsers can reveal a new IP",
     "A household's confirmed browser seen on an unclaimed home IP on two separate days moves the household there. A later TV sighting overrules it.",
     "Medium"),
    ("R6", "Shared networks are ignored",
     "Mobile-carrier, office and public Wi-Fi IPs are never used to link anything, because many households sit behind them.",
     "Guard"),
    ("R7", "Stale addresses are not trusted",
     "If an IP has not been re-confirmed recently, sightings there are held until the next confirmation shows who was really there. If none ever comes, they count only as a weak link.",
     "Guard / weak"),
    ("R8", "New TV ID, same home",
     "When a new TV ID takes over a household's IP, the old ID goes silent and the household's browsers keep appearing there, the two are merged.",
     "Medium"),
]


class Resolver:
    def __init__(self, ip_type, opts):
        self.ip_type = ip_type
        self.confirm_days = int(opts["confirm_days"])
        self.fresh = opts["fresh_days"] * DAY
        self.stale = opts["stale_days"] * DAY
        self.hold = opts["hold_days"] * DAY
        self.move_window = opts["move_window_days"] * DAY

        self.households = {}   # household id -> record
        self.tv_hh = {}        # TV ad ID -> household id
        self.ips = {}          # ip -> {"owner", "last_confirm", "held"}
        self.parent = {}       # union-find over cookies and emails (one person/browser cluster)
        self.evidence = {}     # cluster root -> {household id -> {day -> ts}}
        self.weak = {}         # cluster root -> {household id -> {day -> ts}}   unconfirmed sightings
        self.direct = set()    # cookies that were themselves seen on a home IP
        self.cohab = {}        # (old household, new household) -> set(days)   for R8
        self.evicted_by = {}   # household -> the brand-new household that took its IP
        self.not_home = set()  # (household, ip) pairs the TV has overruled
        self.log = []          # every decision, in order
        self.counts = {}       # rule id -> times it fired
        self.snapshots = {}    # checkpoint day -> {TV ad ID -> IP the graph believed that day}
        self._n = 0

    # ------------------------------------------------------------------ run
    def run(self, events, checkpoints=()):
        cps = sorted(checkpoints)
        i = 0
        for ev in events:
            while i < len(cps) and ev["ts"] >= cps[i] * DAY:
                self._snapshot(cps[i])
                i += 1
            if ev["ctv_id"]:
                self._on_tv(ev)
            else:
                self._on_site(ev)
        while i < len(cps):
            self._snapshot(cps[i])
            i += 1
        return self

    # ------------------------------------------------------------ TV events
    def _on_tv(self, ev):
        ctv, ip, ts = ev["ctv_id"], ev["ip"], ev["ts"]
        hid = self.tv_hh.get(ctv)
        is_new = hid is None
        if is_new:
            self._n += 1
            hid = "HH-%04d" % self._n
            self.households[hid] = {
                "id": hid, "tv_ids": [ctv], "current_ip": None, "ranges": [],
                "last_tv_ts": None, "last_confirm_ts": None, "created_ts": ts,
                "merged_into": None,
            }
            self.tv_hh[ctv] = hid
            self._note(ts, "R1", hid, ip, "New TV ad ID %s seen for the first time. Started household %s." % (ctv, hid))
        hid = self.canon(hid)
        hh = self.households[hid]
        hh["last_tv_ts"] = ts
        if hh["current_ip"] == ip:
            self._confirm(hid, ip, ts)
        else:
            self._claim(hid, ip, ts, "tv", is_new)

    # ---------------------------------------------------------- site events
    def _on_site(self, ev):
        cookie, email, ip, ts = ev["cookie_id"], ev["hashed_email"], ev["ip"], ev["ts"]
        day = ts // DAY
        self.parent.setdefault(cookie, cookie)
        if email:
            self.parent.setdefault(email, email)
            if self._find(cookie) != self._find(email):
                self._union(cookie, email)
                self._note(ts, "R4", None, ip,
                           "Email %s… submitted from browser %s. They are now one person." % (email[:10], cookie),
                           ids=(cookie, email))
        if self.ip_type(ip) != "residential":
            self.counts["R6"] = self.counts.get("R6", 0) + 1
            return
        st = self._ip(ip)
        owner = self.canon(st["owner"]) if st["owner"] else None
        home, level, _ = self.home_of(cookie)

        # A browser we already trust, back on its own household's IP: that
        # re-confirms the address.
        if owner is not None and home == owner and level == "confirmed":
            self._confirm(owner, ip, ts)
            self._credit(cookie, owner, day, ts, ip)
            return

        age = (ts - st["last_confirm"]) if owner is not None else None
        if owner is not None and age <= self.fresh:
            self._credit(cookie, owner, day, ts, ip)
            self._maybe_merge(home, level, owner, day, ts, ip)
            return

        # Nobody has confirmed this address lately (or ever). Hold the
        # sighting until we know who lives here.
        st["held"].append((ts, day, cookie))
        self.counts["R7"] = self.counts.get("R7", 0) + 1
        if owner is not None:
            # The last household known at this address. Unless something
            # confirms it, this only ever counts as a weak link.
            self.weak.setdefault(self._find(cookie), {}).setdefault(owner, {}).setdefault(day, ts)
            self.direct.add(cookie)
        if owner is None or age > self.stale:
            self._maybe_move(home, level, ip, ts, cookie)

    # ------------------------------------------------------------- the rules
    def _claim(self, hid, ip, ts, by, is_new=False):
        """Household `hid` is now at `ip` (R1, R2 or R5)."""
        hh = self.households[hid]
        st = self._ip(ip)
        old_ip = hh["current_ip"]
        overruled = False
        if old_ip is not None:
            r = hh["ranges"][-1]
            before = hh["ranges"][-2]["ip"] if len(hh["ranges"]) > 1 else None
            if by == "tv" and r["opened_by"] == "browser" and before == ip:
                r["status"] = "withdrawn"
                self.not_home.add((hid, old_ip))
                overruled = True
            else:
                r["status"] = "moved"
            r["closed_ts"] = ts
            ost = self.ips[old_ip]
            if ost["owner"] and self.canon(ost["owner"]) == hid:
                ost["owner"] = None

        prev = self.canon(st["owner"]) if st["owner"] else None
        if prev is not None and prev != hid:
            p = self.households[prev]
            p["ranges"][-1]["status"] = "reassigned"
            p["ranges"][-1]["closed_ts"] = ts
            p["current_ip"] = None
            if is_new:
                self.evicted_by[prev] = hid
            self._note(ts, "R2", prev, ip,
                       "IP %s now shows a different household's device. Retired it as %s's address." % (ip, prev))

        # Sightings held on this IP may belong to the household that just
        # arrived - but only those after the previous occupant was last
        # confirmed here and after we were last confirmed somewhere else.
        lower = ts - self.hold
        if prev is not None and prev != hid:
            lower = max(lower, st["last_confirm"])
        if hh["last_confirm_ts"] is not None:
            lower = max(lower, hh["last_confirm_ts"])
        mine = [h for h in st["held"] if h[0] > lower]
        first_seen = min([h[0] for h in mine] + [ts])
        st["held"] = []
        st["owner"] = hid
        st["last_confirm"] = ts
        hh["current_ip"] = ip
        hh["last_confirm_ts"] = ts
        hh["ranges"].append({
            "ip": ip, "first_seen_ts": first_seen, "opened_ts": ts, "last_confirmed_ts": ts,
            "opened_by": by, "confidence": "high" if by == "tv" else "medium",
            "status": "current", "closed_ts": None,
        })
        for hts, hday, hcookie in mine:
            if prev is not None and prev != hid:
                self.weak.get(self._find(hcookie), {}).get(prev, {}).pop(hday, None)
            self._credit(hcookie, hid, hday, hts, ip)

        if is_new:
            pass  # already logged as R1
        elif by == "tv":
            if overruled:
                text = "TV seen back on %s. Overruled the browser-based move to %s." % (ip, old_ip)
            elif old_ip is None:
                text = "TV seen on %s. %s has a known address again." % (ip, hid)
            else:
                text = "TV seen on a new IP. Closed %s, opened %s for %s." % (old_ip, ip, hid)
            self._note(ts, "R2", hid, ip, text)
        else:
            self._note(ts, "R5", hid, ip,
                       "Known browser seen on unclaimed IP %s on two separate days. Moved %s there%s." % (
                           ip, hid, (" from %s" % old_ip) if old_ip else ""))

    def _confirm(self, hid, ip, ts):
        """The household was seen on the IP we already had for it."""
        st = self.ips[ip]
        hh = self.households[hid]
        held, st["held"] = st["held"], []
        st["last_confirm"] = ts
        hh["last_confirm_ts"] = ts
        hh["ranges"][-1]["last_confirmed_ts"] = ts
        for hts, hday, hcookie in held:
            self._credit(hcookie, hid, hday, hts, ip)

    def _credit(self, cookie, hid, day, ts, ip):
        """R3: one more day of evidence that this browser lives in this household."""
        root = self._find(cookie)
        days = self.evidence.setdefault(root, {}).setdefault(hid, {})
        self.direct.add(cookie)
        if day in days:
            return
        days[day] = ts
        if len(days) == 1:
            self._note(ts, "R3", hid, ip,
                       "Browser %s seen on %s's home IP. Linked as probable." % (cookie, hid), ids=(cookie,))
        elif len(days) == self.confirm_days:
            self.counts["R3 confirmed"] = self.counts.get("R3 confirmed", 0) + 1
            self.log.append({"ts": ts, "rule": "R3", "hid": hid, "ip": ip, "ids": (cookie,),
                             "text": "Browser %s seen there again on another day. Link confirmed." % cookie})

    def _maybe_move(self, home, level, ip, ts, cookie):
        """R5: a household's trusted browser keeps turning up on an unclaimed home IP."""
        if home is None or level != "confirmed":
            return
        hh = self.households[home]
        if hh["current_ip"] == ip or (home, ip) in self.not_home:
            return
        # Recent sightings held on this IP that belong to the same person.
        root = self._find(cookie)
        seen = {}
        for hts, hday, hcookie in self.ips[ip]["held"]:
            if ts - hts <= self.move_window and self._find(hcookie) == root:
                seen.setdefault(hday, hts)
        if len(seen) < 2:
            return
        if hh["last_tv_ts"] is not None and hh["last_tv_ts"] >= min(seen.values()):
            return  # the TV has been seen at the old address since - they have not moved
        self._claim(home, ip, ts, "browser")

    def _maybe_merge(self, home, level, owner, day, ts, ip):
        """R8: a new TV ID took over this household's IP and its browsers are still here."""
        if home is None or home == owner or level != "confirmed":
            return
        if self.evicted_by.get(home) != owner:
            return
        if self.households[home]["current_ip"] is not None:
            return
        days = self.cohab.setdefault((home, owner), set())
        days.add(day)
        if len(days) < 2:
            return
        old, new = self.households[home], self.households[owner]
        old["merged_into"] = owner
        new["tv_ids"] = old["tv_ids"] + new["tv_ids"]
        new["ranges"] = sorted(old["ranges"] + new["ranges"], key=lambda r: r["opened_ts"])
        new["created_ts"] = min(old["created_ts"], new["created_ts"])
        self._note(ts, "R8", owner, ip,
                   "%s's browsers keep appearing on %s after a new TV ID took it over, and its old TV ID has gone "
                   "silent. Same home, new TV ID: merged %s into %s." % (home, ip, home, owner))

    # ------------------------------------------------------- lookups / export
    def home_of(self, ident):
        """Which household a cookie or email belongs to, and how sure we are."""
        if ident not in self.parent:
            return None, None, 0
        root = self._find(ident)
        ev = self.evidence.get(root)
        weak_only = not ev
        if weak_only:
            ev = dict((h, d) for h, d in self.weak.get(root, {}).items() if d)
        if not ev:
            return None, None, 0
        tally = {}
        for hid, days in ev.items():
            h = self.canon(hid)
            c, last = tally.get(h, (0, -1))
            tally[h] = (c + len(days), max(last, max(days.values())))
        ranked = sorted(tally.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
        top = ranked[0][1][0]
        runner = ranked[1][1][0] if len(ranked) > 1 else 0
        if weak_only:
            level = "weak"
        else:
            level = "confirmed" if (top >= self.confirm_days and top > runner) else "probable"
        return ranked[0][0], level, top

    def resolve_event(self, ev):
        """Household for one event: (household id, confidence, how)."""
        if ev["ctv_id"]:
            hid = self.tv_hh.get(ev["ctv_id"])
            return (self.canon(hid), "high", "TV ad ID") if hid else (None, None, None)
        home, level, _ = self.home_of(ev["cookie_id"])
        if home is None:
            return None, None, None
        if ev["cookie_id"] not in self.direct:
            how = "email match to another browser"
        elif level == "weak":
            how = "browser seen on a stale address"
        else:
            how = "browser seen at home"
        return home, level, how

    def canon(self, hid):
        while self.households[hid]["merged_into"]:
            hid = self.households[hid]["merged_into"]
        return hid

    def live_households(self):
        return [h for h in self.households.values() if not h["merged_into"]]

    def ip_history(self, hid):
        """A household's IP ranges, with back-to-back ranges on the same IP joined."""
        out = []
        for r in self.households[self.canon(hid)]["ranges"]:
            if r["status"] == "withdrawn":
                continue
            if out and out[-1]["ip"] == r["ip"]:
                out[-1]["last_confirmed_ts"] = max(out[-1]["last_confirmed_ts"], r["last_confirmed_ts"])
                out[-1]["status"] = r["status"]
                out[-1]["closed_ts"] = r["closed_ts"]
            else:
                out.append(dict(r))
        return out

    # ------------------------------------------------------------- internals
    def _snapshot(self, day):
        snap = {}
        for ctv, hid in self.tv_hh.items():
            snap[ctv] = self.households[self.canon(hid)]["current_ip"]
        self.snapshots[day] = snap

    def _ip(self, ip):
        st = self.ips.get(ip)
        if st is None:
            st = self.ips[ip] = {"owner": None, "last_confirm": 0, "held": []}
        return st

    def _note(self, ts, rule, hid, ip, text, ids=()):
        self.counts[rule] = self.counts.get(rule, 0) + 1
        self.log.append({"ts": ts, "rule": rule, "hid": hid, "ip": ip, "text": text, "ids": ids})

    def _find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def _union(self, a, b):
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        for store in (self.evidence, self.weak):
            moved = store.pop(rb, None)
            if moved:
                mine = store.setdefault(ra, {})
                for hid, days in moved.items():
                    target = mine.setdefault(hid, {})
                    for d, t in days.items():
                        target.setdefault(d, t)
