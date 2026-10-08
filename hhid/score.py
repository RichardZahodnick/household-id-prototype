"""Scores the resolver against the answer key, next to raw-IP matching.

Two methods are compared on exactly the same events:

  RAW IP        a conversion is tied to an ad if it came from the same IP
                address an impression was served to.
  HOUSEHOLD ID  a conversion is tied to an ad if the resolver put both on the
                same household ID.

The answer key (which household every event really belongs to) is only used
here, to mark each match as right, wrong or missed.
"""
from .settings import DAY

MISS_REASONS = {
    "mobile": "Converted on mobile data, in a browser never seen on the home network",
    "shared": "Converted on office or public Wi-Fi, in a browser never seen on the home network",
    "guest": "Converted on someone else's home Wi-Fi, in a browser never seen at their own home",
    "home_unconfirmed": "Converted at home, but that address was never confirmed as theirs",
    "tv_reset": "The TV's ad ID was reset and nothing reconnected the old and new ID",
    "wrong_household": "Browser was linked to the wrong household (usually a guest on someone else's Wi-Fi)",
    "stale_address": "Only a weak link through an address that had since changed hands",
}

RAW_MISS_REASONS = {
    "ip_changed": "Converted at home, but the home IP had changed since the ad",
    "away": "Converted away from home (mobile data, office, public Wi-Fi, a friend's house)",
}


def _pct(a, b):
    return (100.0 * a / b) if b else 0.0


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _quantile(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def score(sim, res, cfg):
    total = sim.total_seconds
    days = int(cfg["days"])
    true_hh = {h["id"]: h for h in sim.households}

    # Which resolved household IDs hold each true household's TV(s)?
    true_res = {}
    for h in sim.households:
        ids = set()
        for _, ctv in h["tv_ids"]:
            if ctv in res.tv_hh:
                ids.add(res.canon(res.tv_hh[ctv]))
        true_res[h["id"]] = ids

    # ----------------------------------------------------------- impressions
    true_imps = {}   # true household -> [ts]
    raw_idx = {}     # ip -> [(ts, true household)]
    hh_idx = {}      # resolved household -> [(ts, true household)]
    conversions = []
    n_by_type = {}
    for ev in sim.events:
        n_by_type[ev["event_type"]] = n_by_type.get(ev["event_type"], 0) + 1
        th = sim.truth[ev["event_id"]][0]
        if ev["event_type"] == "impression":
            true_imps.setdefault(th, []).append(ev["ts"])
            raw_idx.setdefault(ev["ip"], []).append((ev["ts"], th))
            rh = res.resolve_event(ev)[0]
            if rh:
                hh_idx.setdefault(rh, []).append((ev["ts"], th))
        elif ev["event_type"] == "conversion":
            conversions.append(ev)

    def judge(matches, th, exposed):
        if exposed:
            if any(m[1] == th for m in matches):
                return "correct"
            return "wrong" if matches else "missed"
        return "false" if matches else "ok"

    def attribute(lookback_days):
        rows = []
        for ev in conversions:
            th, place = sim.truth[ev["event_id"]]
            t = ev["ts"]
            lo = (t - lookback_days * DAY) if lookback_days else -1
            exp_ts = [x for x in true_imps.get(th, []) if lo <= x < t]
            exposed = bool(exp_ts)
            raw_m = [m for m in raw_idx.get(ev["ip"], []) if lo <= m[0] < t]
            rh, conf, how = res.resolve_event(ev)
            hh_m = [m for m in hh_idx.get(rh, []) if lo <= m[0] < t] if rh else []
            rows.append({
                "event_id": ev["event_id"], "ts": t, "ip": ev["ip"], "true_household": th, "place": place,
                "exposed": exposed,
                "gap_days": ((t - max(exp_ts)) / float(DAY)) if exposed else None,
                "raw": judge(raw_m, th, exposed),
                "hh": judge(hh_m, th, exposed),
                "resolved_household": rh, "confidence": conf, "how": how,
                "raw_wrong_owner": sorted(set(m[1] for m in raw_m if m[1] != th)),
            })
        return rows

    def summarise(rows):
        out = {}
        n_exp = sum(1 for r in rows if r["exposed"])
        for m in ("raw", "hh"):
            c = {k: sum(1 for r in rows if r[m] == k) for k in ("correct", "missed", "wrong", "false", "ok")}
            credited = c["correct"] + c["wrong"] + c["false"]
            out[m] = dict(c, exposed=n_exp, unexposed=len(rows) - n_exp, credited=credited,
                          recall=_pct(c["correct"], n_exp),
                          precision=_pct(c["correct"], credited),
                          false_matches=c["wrong"] + c["false"])
        return out

    rows_all = attribute(None)
    rows_30 = attribute(30)
    result = {
        "counts": {
            "households": len(sim.households), "days": days, "events": len(sim.events),
            "tv_ad_requests": n_by_type.get("tv_ad_request", 0), "impressions": n_by_type.get("impression", 0),
            "site_visits": n_by_type.get("site_visit", 0), "conversions": len(conversions),
            "ip_changes": sum(len(h["leases"]) - 1 for h in sim.households),
            "households_exposed": len(true_imps),
        },
        "attribution_all": summarise(rows_all),
        "attribution_30": summarise(rows_30),
        "rows_all": rows_all,
    }

    # ------------------------------------------- recovery by time since the ad
    buckets = []
    edges = list(range(0, 300, 30)) + [300]
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else 10 ** 6
        sel = [r for r in rows_all if r["exposed"] and lo <= r["gap_days"] < hi]
        if not sel:
            continue
        buckets.append({
            "lo": lo, "hi": hi if hi < 10 ** 6 else None, "n": len(sel),
            "raw": _pct(sum(1 for r in sel if r["raw"] == "correct"), len(sel)),
            "hh": _pct(sum(1 for r in sel if r["hh"] == "correct"), len(sel)),
        })
    result["by_gap"] = buckets

    # ------------------------------------------- where the conversion happened
    places = []
    for key, label in (("home", "At home"), ("cellular", "Mobile data"), ("work", "Office Wi-Fi"),
                       ("public", "Public Wi-Fi"), ("friend", "A friend's home")):
        sel = [r for r in rows_all if r["exposed"] and r["place"] == key]
        if sel:
            places.append({"place": label, "n": len(sel),
                           "raw": _pct(sum(1 for r in sel if r["raw"] == "correct"), len(sel)),
                           "hh": _pct(sum(1 for r in sel if r["hh"] == "correct"), len(sel))})
    result["by_place"] = places

    # ------------------------------------------- how good each confidence level is
    tiers = []
    for level in ("confirmed", "probable", "weak"):
        sel = [r for r in rows_all if r["confidence"] == level and r["hh"] in ("correct", "wrong", "false")]
        tiers.append({"level": level, "credited": len(sel),
                      "right": sum(1 for r in sel if r["hh"] == "correct"),
                      "pct": _pct(sum(1 for r in sel if r["hh"] == "correct"), len(sel))})
    result["by_confidence"] = tiers

    # ---------------------------------------------------------- why it missed
    hh_miss, raw_miss = {}, {}
    for r in rows_all:
        if not r["exposed"]:
            continue
        if r["hh"] != "correct":
            if r["resolved_household"] is None:
                key = {"cellular": "mobile", "work": "shared", "public": "shared",
                       "friend": "guest"}.get(r["place"], "home_unconfirmed")
            elif r["resolved_household"] in true_res[r["true_household"]]:
                key = "tv_reset"
            elif r["confidence"] == "weak":
                key = "stale_address"
            else:
                key = "wrong_household"
            hh_miss[key] = hh_miss.get(key, 0) + 1
            r["miss_reason"] = key
        if r["raw"] != "correct":
            key = "ip_changed" if r["place"] == "home" else "away"
            raw_miss[key] = raw_miss.get(key, 0) + 1
    result["hh_misses"] = sorted(hh_miss.items(), key=lambda kv: -kv[1])
    result["raw_misses"] = sorted(raw_miss.items(), key=lambda kv: -kv[1])
    raw_false = {"reassigned": 0, "guest": 0}
    for r in rows_all:
        if r["raw"] in ("wrong", "false"):
            raw_false["guest" if r["place"] == "friend" else "reassigned"] += 1
    result["raw_false_kinds"] = raw_false

    # ------------------------------------- tracking households after the flight
    # Freeze an IP list at the end of the campaign (each household's IP at its
    # last TV sighting) and ask, week by week, whether it still points home.
    camp_end = min(days, int(cfg["campaign"]["start_day"]) + int(cfg["campaign"]["length_days"]))
    listed = {}
    for ev in sim.events:
        if ev["ctv_id"] and ev["ts"] < camp_end * DAY:
            listed[sim.truth[ev["event_id"]][0]] = ev["ip"]
    lease_idx = {}
    for h in sim.households:
        for s, e, ip in h["leases"]:
            lease_idx.setdefault(ip, []).append((s, e, h["id"]))
    tracking = []
    for d in sorted(res.snapshots):
        if d < camp_end:
            continue
        ts = min(d * DAY, total - 1)
        snap = res.snapshots[d]
        raw_ok = raw_other = g_ok = g_wrong = 0
        for h in sim.households:
            true_ip = sim.home_ip(h, ts)
            ip0 = listed.get(h["id"])
            if ip0 is not None:
                if ip0 == true_ip:
                    raw_ok += 1
                elif any(s <= ts < e and hid != h["id"] for s, e, hid in lease_idx.get(ip0, [])):
                    raw_other += 1
            believed = set()
            for from_ts, ctv in h["tv_ids"]:
                if from_ts <= ts and snap.get(ctv):
                    believed.add(snap[ctv])
            if true_ip in believed:
                g_ok += 1
            elif believed:
                g_wrong += 1
        n = len(sim.households)
        tracking.append({"day": d, "since": d - camp_end, "raw": _pct(raw_ok, n), "raw_other": _pct(raw_other, n),
                         "hh": _pct(g_ok, n), "hh_wrong": _pct(g_wrong, n)})
    result["tracking"] = tracking
    result["list_day"] = camp_end
    result["listed_households"] = len(listed)

    # ------------------------------------------------- how fast changes are seen
    lags, by_tv, by_browser, n_changes = [], 0, 0, 0
    for h in sim.households:
        ranges = []
        for rid in true_res[h["id"]]:
            ranges.extend(res.households[rid]["ranges"])
        for k in range(1, len(h["leases"])):
            s, e, ip = h["leases"][k]
            n_changes += 1
            hits = [r for r in ranges if r["ip"] == ip and s <= r["opened_ts"] < e and r["status"] != "withdrawn"]
            if hits:
                first = min(hits, key=lambda r: r["opened_ts"])
                lags.append((first["opened_ts"] - s) / float(DAY))
                if first["opened_by"] == "tv":
                    by_tv += 1
                else:
                    by_browser += 1
    result["detection"] = {
        "changes": n_changes, "detected": len(lags), "detected_pct": _pct(len(lags), n_changes),
        "median_lag_days": _median(lags), "p90_lag_days": _quantile(lags, 0.9),
        "by_tv": by_tv, "by_browser": by_browser,
    }

    # ------------------------------------------------------- identity quality
    link = {"confirmed": [0, 0], "probable": [0, 0], "weak": [0, 0], "unlinked": 0}
    for cookie, th in sim.cookie_owner.items():
        home, level, _ = res.home_of(cookie)
        if home is None:
            link["unlinked"] += 1
            continue
        link[level][1] += 1
        if home in true_res[th]:
            link[level][0] += 1
    live = res.live_households()
    merged_wrong = 0
    for hh in live:
        owners = set(sim.tv_owner[c] for c in hh["tv_ids"])
        if len(owners) > 1:
            merged_wrong += 1
    result["identity"] = {
        "true_households": len(sim.households),
        "seen_households": sum(1 for h in sim.households if true_res[h["id"]]),
        "resolved_households": len(live),
        "split": sum(1 for h in sim.households if len(true_res[h["id"]]) > 1),
        "tv_resets": sum(len(h["tv_ids"]) - 1 for h in sim.households),
        "merged_wrong": merged_wrong,
        "cookies": len(sim.cookie_owner),
        "link": link,
        "bridged_by_email": sum(1 for r in rows_all if r["how"] == "email match to another browser"),
    }
    result["rule_counts"] = dict(res.counts)

    result["story"] = _pick_story(sim, res, rows_all, true_hh, true_res)
    return result


def _pick_story(sim, res, rows, true_hh, true_res):
    """Find one household that shows the whole idea end to end."""
    best = None
    for r in rows:
        if not (r["exposed"] and r["hh"] == "correct" and r["raw"] == "missed" and r["place"] == "home"):
            continue
        h = true_hh[r["true_household"]]
        if len(h["tv_ids"]) != 1 or len(true_res[h["id"]]) != 1:
            continue
        last_imp = r["ts"] - r["gap_days"] * DAY
        moves = sum(1 for s, e, ip in h["leases"][1:] if last_imp < s <= r["ts"])
        if moves < 2 or moves > 4 or r["gap_days"] < 90:
            continue
        hist = res.ip_history(next(iter(true_res[h["id"]])))
        true_ips = [l[2] for l in h["leases"]]
        if [x["ip"] for x in hist] != true_ips:
            continue  # prefer a household the graph followed cleanly
        key = (moves == 2 or moves == 3, r["gap_days"], h["id"])
        if best is None or key > best[0]:
            best = (key, r, h)
    if best is None:
        for r in rows:
            if r["exposed"] and r["hh"] == "correct" and r["raw"] == "missed" and r["place"] == "home":
                h = true_hh[r["true_household"]]
                if len(true_res[h["id"]]) == 1:
                    best = ((False, r["gap_days"], h["id"]), r, h)
                    break
    if best is None:
        return None
    _, r, h = best
    rid = next(iter(true_res[h["id"]]))
    cookies = set(c for c, owner in sim.cookie_owner.items() if owner == h["id"])
    emails = set(p["email"] for p in h["people"])
    events = [dict(ev, place=sim.truth[ev["event_id"]][1]) for ev in sim.events
              if sim.truth[ev["event_id"]][0] == h["id"]]
    log = [e for e in res.log
           if (e["hid"] is not None and res.canon(e["hid"]) == rid) or (set(e["ids"]) & (cookies | emails))]
    log = [dict(e, elsewhere=(e["rule"] == "R3" and e["hid"] is not None and res.canon(e["hid"]) != rid)) for e in log]
    log.sort(key=lambda e: e["ts"])
    return {
        "true_id": h["id"], "resolved_id": rid, "conversion": r,
        "leases": h["leases"], "history": res.ip_history(rid),
        "events": events, "log": log, "tv_platform": h["tv_platform"], "people": len(h["people"]),
    }
