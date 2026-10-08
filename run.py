#!/usr/bin/env python3
"""Household ID prototype - run the whole thing with:

    python3 run.py

It simulates a year of households, resolves them into household IDs, scores
that against raw-IP matching using the answer key, and writes a report to
output/report.html.

Change any setting for one run without editing config.json:

    python3 run.py --set ip_changes.speed=4
    python3 run.py --set tv.ad_requests_visible_all_year=false
    python3 run.py --set seed=3 --set households=1000
"""
import argparse
import copy
import csv
import json
import os
import sys
from datetime import datetime, timedelta

sys.dont_write_bytecode = True  # keep the project folder free of __pycache__

from hhid import report, resolve, score, settings, simulate  # noqa: E402
from hhid.settings import DAY  # noqa: E402,F401


def run_once(cfg):
    sim = simulate.simulate(cfg)
    camp_end = min(int(cfg["days"]), int(cfg["campaign"]["start_day"]) + int(cfg["campaign"]["length_days"]))
    checkpoints = list(range(camp_end, int(cfg["days"]) + 1, 7))
    # The resolver gets the event log and an IP-type lookup. Nothing else.
    res = resolve.Resolver(simulate.ip_type, cfg["resolver"]).run(sim.events, checkpoints)
    return sim, res, score.score(sim, res, cfg)


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="Household ID prototype")
    ap.add_argument("--config", default=settings.default_path())
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a setting for this run, e.g. ip_changes.speed=4")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    ap.add_argument("--no-compare", action="store_true", help="skip the advertiser-only comparison run")
    args = ap.parse_args()

    cfg = settings.load(args.config)
    for item in args.set:
        try:
            key, old, new = settings.apply_override(cfg, item)
        except ValueError as e:
            sys.exit(str(e))
        print("setting %s: %s -> %s" % (key, old, new))

    sim, res, result = run_once(cfg)

    alt = None
    if not args.no_compare and cfg["tv"]["ad_requests_visible_all_year"]:
        cfg2 = copy.deepcopy(cfg)
        cfg2["tv"]["ad_requests_visible_all_year"] = False
        alt = run_once(cfg2)[2]

    start = datetime.strptime(cfg["start_date"], "%Y-%m-%d")

    def iso(ts):
        return (start + timedelta(seconds=int(ts))).strftime("%Y-%m-%d %H:%M:%S")

    out = args.out
    key_dir = os.path.join(out, "answer_key")
    os.makedirs(key_dir, exist_ok=True)

    # What the system sees.
    write_csv(os.path.join(out, "events.csv"),
              ["event_id", "timestamp", "event_type", "ip", "ctv_id", "cookie_id", "hashed_email"],
              [[e["event_id"], iso(e["ts"]), e["event_type"], e["ip"], e["ctv_id"], e["cookie_id"], e["hashed_email"]]
               for e in sim.events])

    # What the system built.
    rows = []
    for hh in sorted(res.live_households(), key=lambda h: h["id"]):
        for r in res.ip_history(hh["id"]):
            rows.append([hh["id"], r["ip"], iso(r["first_seen_ts"]), iso(r["last_confirmed_ts"]),
                         {"tv": "TV ad ID", "browser": "known browser"}[r["opened_by"]], r["confidence"], r["status"]])
    write_csv(os.path.join(out, "household_ip_history.csv"),
              ["household_id", "ip", "first_seen", "last_confirmed", "found_by", "confidence", "status"], rows)
    write_csv(os.path.join(out, "decision_log.csv"), ["timestamp", "rule", "household_id", "ip", "decision"],
              [[iso(e["ts"]), e["rule"], e["hid"] or "", e["ip"], e["text"]] for e in sorted(res.log, key=lambda e: e["ts"])])

    # How it scored.
    write_csv(os.path.join(out, "conversions_scored.csv"),
              ["event_id", "timestamp", "ip", "resolved_household", "confidence", "how_linked", "true_household",
               "where_they_were", "household_saw_ad", "days_since_ad", "raw_ip_result", "household_id_result"],
              [[r["event_id"], iso(r["ts"]), r["ip"], r["resolved_household"] or "", r["confidence"] or "", r["how"] or "",
                r["true_household"], r["place"], "yes" if r["exposed"] else "no",
                "" if r["gap_days"] is None else "%.1f" % r["gap_days"], r["raw"], r["hh"]] for r in result["rows_all"]])

    # The answer key (never read by the resolver).
    write_csv(os.path.join(key_dir, "households.csv"),
              ["true_household", "people", "ip_change_pattern", "tv_viewing", "in_campaign_audience", "tv_ad_ids"],
              [[h["id"], len(h["people"]), h["lease_class"], h["tv_class"], "yes" if h["targeted"] else "no",
                " ".join(c for _, c in h["tv_ids"])] for h in sim.households])
    write_csv(os.path.join(key_dir, "ip_leases.csv"), ["true_household", "ip", "from", "to"],
              [[h["id"], ip, iso(s), iso(min(e, sim.total_seconds - 1))] for h in sim.households for s, e, ip in h["leases"]])
    write_csv(os.path.join(key_dir, "event_truth.csv"), ["event_id", "true_household", "where"],
              [[eid, t[0], t[1]] for eid, t in sim.truth.items()])

    summary = {k: result[k] for k in ("counts", "attribution_all", "attribution_30", "by_gap", "by_place", "by_confidence",
                                      "hh_misses", "raw_misses", "raw_false_kinds", "tracking", "detection", "identity",
                                      "rule_counts")}
    if alt:
        summary["advertiser_only_view"] = {k: alt[k] for k in ("attribution_all", "by_confidence", "detection")}
    summary["settings"] = cfg
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    report_path = os.path.join(out, "report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report.build(cfg, result, alt, sim.total_seconds))

    A = result["attribution_all"]
    c = result["counts"]
    det = result["detection"]
    trk = result["tracking"]
    print("")
    print("Simulated %d households over %d days: %d IP changes, %d impressions, %d conversions." % (
        c["households"], c["days"], c["ip_changes"], c["impressions"], c["conversions"]))
    print("")
    print("Conversions from ad-exposed homes tied back to the right ad (whole year):")
    print("  Household ID   %5.1f%%   (%d of %d, %d credited to the wrong home)" % (
        A["hh"]["recall"], A["hh"]["correct"], A["hh"]["exposed"], A["hh"]["false_matches"]))
    print("  Raw IP         %5.1f%%   (%d of %d, %d credited to the wrong home)" % (
        A["raw"]["recall"], A["raw"]["correct"], A["raw"]["exposed"], A["raw"]["false_matches"]))
    if trk:
        print("")
        print("Households still located correctly %d weeks after the campaign:" % round(trk[-1]["since"] / 7.0))
        print("  Household ID   %5.1f%%" % trk[-1]["hh"])
        print("  Frozen IP list %5.1f%%" % trk[-1]["raw"])
    print("")
    print("IP changes noticed: %.1f%% of %d, typically within %.1f days." % (
        det["detected_pct"], det["changes"], det["median_lag_days"] or 0))
    if alt:
        B = alt["attribution_all"]
        print("")
        print("Same year, advertiser-only view (TV seen only during the campaign):")
        print("  Household ID   %5.1f%%     Raw IP   %5.1f%%" % (B["hh"]["recall"], B["raw"]["recall"]))
    print("")
    print("Report: %s" % report_path)


if __name__ == "__main__":
    main()
