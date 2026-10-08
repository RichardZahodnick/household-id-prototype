# Household ID Prototype

**The question:** How would you track households over a long period of time if their IP addresses keep changing?

**The short answer:** Stop treating the IP as the household. Give each household a stable ID, store every IP as a dated pointer to that ID, and move the pointer when something already tied to the household (its TV, a known browser, an email) shows up on a new address. You never work out the new IP from the old one. You recognize it when a known identifier is seen on it.

This repo is a working prototype of that idea. It simulates a year of connected TV (CTV) ad exposure and website activity, builds household IDs from the event log, and scores the result against plain raw-IP matching. The data is simulated on purpose: it means the true household behind every event is known, so both approaches can be graded against the right answer.

## Run it

```
python3 run.py
```

That's all. It needs Python 3.9 or newer and nothing else: no installs, no API keys, no network. It takes about two seconds and writes `output/report.html`. Open that file in a browser.

The same settings and seed always produce exactly the same numbers.

## What the default run shows

One simulated year: 600 households, 2,508 home IP changes, a 60-day ad campaign at the start of the year, and 925 conversions spread across all twelve months.

| | Household ID | Raw IP |
|---|---|---|
| Conversions from ad-exposed homes tied back to the right ad (whole year) | **86%** (516 of 603) | 32% (190 of 603) |
| Conversions credited to the wrong household | 23 | 87 |
| Share of matches that were right | 96% | 69% |
| Same test with a standard 30-day lookback | 88% | 56% |
| Households still located correctly 43 weeks after the campaign | **94%** | 21% |

Other things the report shows:

- **Raw IP holds up inside 30 days and falls apart after.** Most home IPs have not changed yet in the first month. By ten months, most have.
- **A stale IP is worse than a missing one.** By year end, 22% of the campaign's IP list points at a *different* household that was handed the old address.
- **IP changes were noticed in about 1.2 days** (median), and 89% of all changes were picked up.
- **About 40% of conversions happen away from the home network** (mobile data, office, a friend's house). Raw IP can never match those. The household ID recovers most of them through cookies and emails.
- **It depends on a steady stream of sightings.** Rerun with an advertiser-only view, where the TV is seen only while the campaign is live, and the household ID drops to 57% (raw IP stays at 32%). A household ID is only as current as the data feeding it.

## How it works

There are three parts, and they are kept separate on purpose.

1. **The simulator** (`hhid/simulate.py`) invents households, their TVs, phones and laptops, their changing home IPs, and a year of events. It produces two things: the event log, and an answer key.
2. **The resolver** (`hhid/resolve.py`) reads only the event log, in time order, plus a lookup that says whether an IP is home broadband, mobile or business (the kind of lookup that is sold commercially). It never sees the answer key. It builds household IDs and a dated IP history for each one.
3. **The scorer** (`hhid/score.py`) uses the answer key to grade the resolver and raw-IP matching on the same events.

### The linking rules

| | Rule | Confidence |
|---|---|---|
| R1 | **A TV anchors a household.** A new TV ad ID starts a new household at that IP. TVs do not leave the house. | High |
| R2 | **A known TV on a new IP moves the household.** The old IP range is closed and a new one opened. | High |
| R3 | **Browsers join the home they are seen in.** One day on a household's home IP is a probable link. Two or more separate days is confirmed. | Probable / confirmed |
| R4 | **An email ties browsers together.** The same hashed email on two cookies means the same person. This survives cookie clearing and IP changes. | High |
| R5 | **Known browsers can reveal a new IP.** A household's confirmed browser seen on an unclaimed home IP on two separate days moves the household there. The TV overrules it. | Medium |
| R6 | **Shared networks are ignored.** Mobile-carrier, office and public Wi-Fi IPs are never used to link anything. | Guard |
| R7 | **Stale addresses are not trusted.** Sightings on an IP nobody has re-confirmed lately are held until someone does. If nobody does, they count only as a weak link. | Guard / weak |
| R8 | **New TV ID, same home.** If a new TV ID takes over a household's IP, the old ID goes silent and the household's browsers keep appearing there, the two are merged. | Medium |

Every link carries a confidence level, so a report can be cut to confirmed links only.

## Change the assumptions

All the knobs are in `config.json`. You can also override any of them for a single run:

```
python3 run.py --set ip_changes.speed=4                       # IPs change four times as often
python3 run.py --set ip_changes.speed=0.25                    # IPs change a quarter as often
python3 run.py --set tv.ad_requests_visible_all_year=false    # advertiser-only view
python3 run.py --set site.cookie_avg_life_days=14             # cookies cleared much sooner
python3 run.py --set seed=3 --set households=1000             # a different, bigger world
```

| Setting | Household ID | Raw IP |
|---|---|---|
| Default | 86% | 32% |
| IPs change 4x as often | 81% | 14% |
| IPs change a quarter as often | 87% | 44% |
| Advertiser-only view | 57% | 32% |

The main groups of settings:

- `campaign`: when the flight runs, how long, and what share of households it reaches.
- `ip_changes`: how often home IPs change (three groups of households: stable, typical, frequent), and how many spare addresses there are. Fewer spare addresses means freed IPs get handed to other homes sooner.
- `tv`: how often each TV is seen, how often TV ad IDs get reset, and whether the system sees TV ad requests all year or only during the campaign.
- `site`: how often people visit, how often they convert, how long cookies last.
- `where_people_browse`: the mix of home Wi-Fi, mobile data, office, public Wi-Fi and friends' houses.
- `resolver`: the thresholds the rules use (days needed to confirm a link, how long an address stays trusted).

## What ends up in `output/`

| File | What it is |
|---|---|
| `report.html` | The report. Open this first. |
| `events.csv` | The event log: everything the system is allowed to see. |
| `household_ip_history.csv` | The dated IP history the system built for every household ID. |
| `decision_log.csv` | Every decision the resolver made, in order, with the rule that made it. |
| `conversions_scored.csv` | Every conversion, how each method handled it, and the true answer. |
| `summary.json` | All the headline numbers in one file. |
| `answer_key/` | The truth: real households, real IP leases, and the true household behind every event. The resolver never reads this folder. |

## What this is not

- **It is not real data.** Every household, IP, cookie and email is invented. IPs come from ranges reserved for testing (`198.18.0.0/15`, `100.64.0.0/10`, `192.0.2.0/24`), so they cannot belong to anyone. The hashed emails are hashes of made-up addresses.
- **It does not measure whether ads work.** No ad effect is modeled. The test is whether an exposure and a later conversion can be connected to the same household, not whether one caused the other.
- **The results depend on the assumptions.** How often IPs change and how often freed addresses are reused are settings, not facts. That is why they are easy to change.
- **Some real-world problems are left out:** TVs with ad tracking limited, homes with several TVs, phone numbers, postal addresses and CRM IDs, VPNs and Apple Private Relay, IPv6 privacy addresses, and an IP-type lookup that sometimes gets it wrong.
- **Consent is not modeled.** A real version has to honor opt-outs and treat IPs, device IDs and hashed emails as personal information under state privacy laws.
- **It is not production code.** It is one process reading one file in memory. The point is the idea and the evidence for it.

## Layout

```
run.py              runs everything
config.json         all the settings
hhid/
  simulate.py       makes the event log and the answer key
  resolve.py        builds household IDs from the event log (the rules live here)
  score.py          grades both methods against the answer key
  report.py         writes the HTML report
  settings.py       loads settings and applies --set overrides
output/             created when you run it
```
