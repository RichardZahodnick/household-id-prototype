"""Builds the single-file HTML report (no external files, no network)."""
import json
from datetime import datetime, timedelta
from html import escape as esc

from .resolve import RULES
from .score import MISS_REASONS, RAW_MISS_REASONS
from .settings import DAY

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;
--seg-a:#b7d3f6;--seg-b:#86b6ef;--seg-ink:#0d366b;--wash:rgba(42,120,214,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--seg-a:#184f95;--seg-b:#1c5cab;--seg-ink:#cde2fb;--wash:rgba(57,135,229,.12)}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--seg-a:#184f95;--seg-b:#1c5cab;
--seg-ink:#cde2fb;--wash:rgba(57,135,229,.12)}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:40px 16px 72px}
h1{font-size:34px;line-height:1.15;margin:8px 0 16px;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:22px;line-height:1.25;margin:0 0 6px;text-wrap:balance}
h3{font-size:16px;margin:24px 0 8px}
p{margin:0 0 12px;max-width:72ch}
.eyebrow{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2);margin:0}
.lede{font-size:18px;color:var(--ink2)}
.lede strong{color:var(--ink)}
section{margin-top:44px}
.sub{color:var(--ink2);margin-bottom:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px}
.hero{display:grid;grid-template-columns:1.25fr 1fr;gap:16px;align-items:stretch}
.hero>.card{display:flex;flex-direction:column;justify-content:center}
.hero .big{font-size:64px;font-weight:650;line-height:1;letter-spacing:-.02em}
.hero .vs{margin-top:14px;padding-top:14px;border-top:1px solid var(--grid);color:var(--ink2)}
.hero .vs b{color:var(--ink);font-size:22px;font-weight:650;margin-right:6px}
.key{display:inline-block;width:18px;height:0;border-top:3px solid var(--s1);border-radius:2px;vertical-align:middle;margin-right:8px}
.key.k2{border-color:var(--s2)}
.tiles{display:grid;grid-template-columns:1fr;gap:12px}
.tile .label{font-size:14px;color:var(--ink2)}
.tile .value{font-size:28px;font-weight:650;line-height:1.2}
.tile .delta{font-size:14px;color:var(--ink2)}
.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:14px;color:var(--ink2);margin:0 0 4px}
.chart{position:relative}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart svg:focus{outline:2px solid var(--s1);outline-offset:4px;border-radius:6px}
.gridline{stroke:var(--grid);stroke-width:1}
.axisline{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.atitle{fill:var(--ink2);font-size:12px}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.l1{stroke:var(--s1)}.l2{stroke:var(--s2)}
.d1{fill:var(--s1)}.d2{fill:var(--s2)}
.dot{stroke:var(--surface);stroke-width:2}
.endv{fill:var(--ink);font-size:15px;font-weight:650}
.endn{fill:var(--ink2);font-size:12px}
.xh{stroke:var(--axis);stroke-width:1;visibility:hidden}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;
padding:8px 10px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.12);visibility:hidden;min-width:150px;z-index:2}
.tip .th{color:var(--ink2);margin-bottom:4px}
.tip .tr{display:flex;align-items:center;gap:6px;white-space:nowrap}
.tip .tr b{font-weight:650;min-width:38px}
.tip .tr span.n{color:var(--ink2)}
.takeaway{margin-top:12px;color:var(--ink2);font-size:15px}
.takeaway strong{color:var(--ink)}
details{margin-top:10px}
summary{cursor:pointer;color:var(--ink2);font-size:14px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600;font-size:13px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.hl td{background:var(--wash)}
td.rule{white-space:nowrap;color:var(--ink2)}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--wash);padding:1px 5px;border-radius:4px}
pre{font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--surface);border:1px solid var(--border);
border-radius:8px;padding:12px;overflow-x:auto}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.seg-a{fill:var(--seg-a)}.seg-b{fill:var(--seg-b)}
.seglabel{fill:var(--seg-ink);font-size:12px;font-weight:650}
.lane{fill:var(--ink2);font-size:12px}
.mark-imp{fill:var(--s1);stroke:var(--surface);stroke-width:1.5}
.mark-visit{fill:var(--muted);stroke:var(--surface);stroke-width:1.5}
.mark-conv{fill:var(--s2);stroke:var(--surface);stroke-width:2}
.swatch{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.swatch.imp{background:var(--s1)}.swatch.visit{background:var(--muted)}
.swatch.conv{background:var(--s2);border-radius:2px;transform:rotate(45deg)}
ul{margin:0 0 12px;padding-left:20px;max-width:72ch}
li{margin-bottom:6px}
footer{margin-top:48px;color:var(--muted);font-size:13px}
@media (max-width:760px){.hero,.two{grid-template-columns:1fr}h1{font-size:28px}.hero .big{font-size:52px}}
"""

JS = """
(function(){
  document.querySelectorAll('.chart[data-chart]').forEach(function(box){
    var d = JSON.parse(box.getAttribute('data-chart'));
    var svg = box.querySelector('svg'), xh = box.querySelector('.xh'), tip = box.querySelector('.tip');
    var cur = -1;
    function show(i){
      if(i < 0 || i >= d.xs.length) return;
      cur = i;
      xh.setAttribute('x1', d.xs[i]); xh.setAttribute('x2', d.xs[i]); xh.style.visibility = 'visible';
      while(tip.firstChild) tip.removeChild(tip.firstChild);
      var h = document.createElement('div'); h.className = 'th'; h.textContent = d.tips[i]; tip.appendChild(h);
      d.series.forEach(function(s, k){
        var r = document.createElement('div'); r.className = 'tr';
        var key = document.createElement('span'); key.className = 'key' + (k ? ' k2' : '');
        var b = document.createElement('b'); b.textContent = s.values[i].toFixed(0) + '%';
        var n = document.createElement('span'); n.className = 'n'; n.textContent = s.name;
        r.appendChild(key); r.appendChild(b); r.appendChild(n); tip.appendChild(r);
      });
      var rect = svg.getBoundingClientRect(), scale = rect.width / d.w;
      var px = d.xs[i] * scale, left = px + 14;
      if(left + tip.offsetWidth > rect.width) left = px - tip.offsetWidth - 14;
      tip.style.left = Math.max(0, left) + 'px'; tip.style.top = (d.top * scale + 4) + 'px';
      tip.style.visibility = 'visible';
    }
    function hide(){ xh.style.visibility = 'hidden'; tip.style.visibility = 'hidden'; cur = -1; }
    svg.addEventListener('pointermove', function(e){
      var rect = svg.getBoundingClientRect(), x = (e.clientX - rect.left) * d.w / rect.width, best = 0;
      for(var i = 1; i < d.xs.length; i++){ if(Math.abs(d.xs[i] - x) < Math.abs(d.xs[best] - x)) best = i; }
      show(best);
    });
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('blur', hide);
    svg.addEventListener('focus', function(){ show(cur < 0 ? d.xs.length - 1 : cur); });
    svg.addEventListener('keydown', function(e){
      if(e.key === 'ArrowLeft'){ show(Math.max(0, cur - 1)); e.preventDefault(); }
      if(e.key === 'ArrowRight'){ show(Math.min(d.xs.length - 1, cur + 1)); e.preventDefault(); }
    });
  });
})();
"""


def _n(x):
    return "{:,}".format(int(round(x)))


def _count(n, word):
    return "%s %s%s" % (_n(n), word, "" if n == 1 else "s")


def _p(x, digits=0):
    return ("%." + str(digits) + "f%%") % x


class Dates:
    def __init__(self, cfg):
        self.start = datetime.strptime(cfg["start_date"], "%Y-%m-%d")

    def day(self, ts):
        d = self.start + timedelta(seconds=int(ts))
        return "%s %d" % (d.strftime("%b"), d.day)

    def full(self, ts):
        d = self.start + timedelta(seconds=int(ts))
        return "%s %d, %d" % (d.strftime("%b"), d.day, d.year)


# ------------------------------------------------------------------ line chart
def line_chart(x_ticks, tips, series, x_title, aria):
    """series: [(name, [values 0-100])]. x_ticks: [(index, label)]. Returns HTML."""
    W, H = 760, 330
    L, R, T, B = 46, 150, 16, 50
    pw, ph = W - L - R, H - T - B
    n = len(tips)
    xs = [L + (pw * i / float(n - 1) if n > 1 else pw / 2.0) for i in range(n)]

    def y(v):
        return T + ph * (1 - v / 100.0)

    out = ['<svg viewBox="0 0 %d %d" role="img" tabindex="0" aria-label="%s">' % (W, H, esc(aria))]
    for v in (0, 25, 50, 75, 100):
        cls = "axisline" if v == 0 else "gridline"
        out.append('<line class="%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (cls, L, L + pw, y(v), y(v)))
        out.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%d%%</text>' % (L - 8, y(v) + 4, v))
    for i, label in x_ticks:
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (xs[i], T + ph + 18, esc(label)))
    out.append('<text class="atitle" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (L + pw / 2.0, H - 6, esc(x_title)))
    out.append('<line class="xh" x1="0" x2="0" y1="%d" y2="%d"/>' % (T, T + ph))
    ends = []
    for k, (name, values) in enumerate(series):
        pts = " ".join("%.1f,%.1f" % (xs[i], y(v)) for i, v in enumerate(values))
        out.append('<polyline class="line l%d" points="%s"/>' % (k + 1, pts))
        out.append('<circle class="dot d%d" cx="%.1f" cy="%.1f" r="5"/>' % (k + 1, xs[-1], y(values[-1])))
        ends.append([y(values[-1]), name, values[-1]])
    # End labels: value + name, kept at least 36px apart so they never overlap.
    order = sorted(range(len(ends)), key=lambda k: ends[k][0])
    for a, b in zip(order, order[1:]):
        if ends[b][0] - ends[a][0] < 36:
            mid = (ends[a][0] + ends[b][0]) / 2.0
            ends[a][0], ends[b][0] = mid - 18, mid + 18
    for ypos, name, value in ends:
        ypos = min(max(ypos, T + 6), T + ph - 14)
        out.append('<text class="endv" x="%.1f" y="%.1f">%s</text>' % (xs[-1] + 12, ypos + 1, _p(value)))
        out.append('<text class="endn" x="%.1f" y="%.1f">%s</text>' % (xs[-1] + 12, ypos + 16, esc(name)))
    out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="transparent"/>' % (L, T, pw, ph))
    out.append("</svg>")
    data = {"w": W, "top": T, "xs": [round(x, 1) for x in xs], "tips": tips,
            "series": [{"name": nm, "values": [round(v, 1) for v in vals]} for nm, vals in series]}
    legend = '<div class="legend">%s</div>' % "".join(
        '<span><span class="key%s"></span>%s</span>' % (" k2" if k else "", esc(nm)) for k, (nm, _) in enumerate(series))
    return '%s<div class="chart" data-chart="%s">%s<div class="tip"></div></div>' % (
        legend, esc(json.dumps(data), quote=True), "".join(out))


def table(headers, rows, num_cols=(), highlight=()):
    h = "".join('<th%s>%s</th>' % (' class="num"' if i in num_cols else "", esc(x)) for i, x in enumerate(headers))
    body = []
    for r_i, r in enumerate(rows):
        cells = "".join('<td%s>%s</td>' % (' class="num"' if i in num_cols else "", x) for i, x in enumerate(r))
        body.append('<tr%s>%s</tr>' % (' class="hl"' if r_i in highlight else "", cells))
    return '<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (h, "".join(body))


# -------------------------------------------------------------- story timeline
def story_block(story, dates, total):
    conv = story["conversion"]
    leases = story["leases"]
    letters = {}
    for _, _, ip in leases:
        letters.setdefault(ip, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[len(letters) % 26])
    for r in story["history"]:
        letters.setdefault(r["ip"], "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[len(letters) % 26])

    W, L, R = 760, 150, 16
    pw = W - L - R

    def x(ts):
        return L + pw * min(max(ts, 0), total) / float(total)

    svg = ['<svg viewBox="0 0 %d 174" role="img" aria-label="Timeline of one household: its real IP addresses, '
           'the IP history the system built, and its ad impressions, site visits and conversion.">' % W]
    # month ticks
    start = dates.start
    m = datetime(start.year, start.month, 1)
    while True:
        m = datetime(m.year + (m.month // 12), (m.month % 12) + 1, 1)
        ts = (m - start).total_seconds()
        if ts >= total:
            break
        svg.append('<line class="gridline" x1="%.1f" x2="%.1f" y1="18" y2="150"/>' % (x(ts), x(ts)))
        svg.append('<text class="tick" x="%.1f" y="166" text-anchor="middle">%s</text>' % (x(ts), m.strftime("%b")))

    def lane(ypos, label1, label2, segs):
        svg.append('<text class="lane" x="0" y="%d">%s</text>' % (ypos + 13, esc(label1)))
        svg.append('<text class="tick" x="0" y="%d">%s</text>' % (ypos + 27, esc(label2)))
        for i, (s, e, ip) in enumerate(segs):
            x0, x1 = x(s), x(e)
            w = max(1.0, x1 - x0 - 2)
            svg.append('<rect class="seg-%s" x="%.1f" y="%d" width="%.1f" height="22" rx="3"><title>%s: %s to %s</title></rect>' % (
                "ab"[i % 2], x0, ypos, w, esc(ip), dates.day(s), dates.day(min(e, total - 1))))
            if w >= 16:
                svg.append('<text class="seglabel" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (
                    x0 + w / 2.0, ypos + 15, letters[ip]))

    lane(22, "Real home IP", "answer key, hidden", leases)
    hist = story["history"]
    segs = []
    for i, r in enumerate(hist):
        end = hist[i + 1]["first_seen_ts"] if i + 1 < len(hist) else (r["closed_ts"] or total)
        segs.append((r["first_seen_ts"], end, r["ip"]))
    lane(62, "IP history the", "system built", segs)
    svg.append('<text class="lane" x="0" y="118">Events</text>')
    svg.append('<line class="axisline" x1="%d" x2="%d" y1="114" y2="114"/>' % (L, L + pw))
    imps = [e for e in story["events"] if e["event_type"] == "impression"]
    visits = [e for e in story["events"] if e["event_type"] == "site_visit"]
    for e in imps:
        svg.append('<circle class="mark-imp" cx="%.1f" cy="114" r="4.5"><title>Ad impression, %s, %s</title></circle>' % (
            x(e["ts"]), dates.day(e["ts"]), esc(e["ip"])))
    for e in visits:
        svg.append('<circle class="mark-visit" cx="%.1f" cy="114" r="4.5"><title>Site visit, %s, %s</title></circle>' % (
            x(e["ts"]), dates.day(e["ts"]), esc(e["ip"])))
    for e in story["events"]:
        if e["event_type"] == "conversion":
            cx = x(e["ts"])
            svg.append('<rect class="mark-conv" x="%.1f" y="107" width="14" height="14" rx="2" transform="rotate(45 %.1f 114)">'
                       '<title>Conversion, %s, %s</title></rect>' % (cx - 7, cx, dates.day(e["ts"]), esc(e["ip"])))
    svg.append("</svg>")
    legend = ('<div class="legend"><span><span class="swatch imp"></span>Ad impression</span>'
              '<span><span class="swatch visit"></span>Site visit</span>'
              '<span><span class="swatch conv"></span>Conversion</span></div>')

    # IP key: what really happened vs when the system noticed
    key_rows = []
    by_ip = {}
    for r in hist:
        by_ip.setdefault(r["ip"], r)
    for i, (s, e, ip) in enumerate(leases):
        r = by_ip.get(ip)
        if r is None:
            noticed, lag = "Never seen", "–"
        elif i == 0:
            noticed, lag = dates.day(r["opened_ts"]), "first sighting"
        else:
            lag_days = (r["opened_ts"] - s) / float(DAY)
            noticed = dates.day(r["opened_ts"])
            lag = "%.1f days" % lag_days if lag_days >= 0 else "–"
        key_rows.append(["<strong>%s</strong>" % letters[ip], "<code>%s</code>" % esc(ip),
                         "%s – %s" % (dates.day(s), dates.day(min(e, total - 1))), noticed, lag])
    key_table = table(["", "IP address", "Really in use", "System first saw it", "Time to notice"], key_rows, num_cols=(4,))

    # Decision log, trimmed to the moments that matter
    rows = []
    last_imp = max(imps, key=lambda e: e["ts"]) if imps else None
    imp_ips = sorted(set(letters.get(e["ip"], "?") for e in imps))
    added_imps = False
    for entry in story["log"]:
        if imps and not added_imps and entry["ts"] > imps[0]["ts"]:
            rows.append((imps[0]["ts"], "Campaign",
                         "%d ad impressions served to this TV between %s and %s, all on IP %s." % (
                             len(imps), dates.day(imps[0]["ts"]), dates.day(last_imp["ts"]), " and ".join(imp_ips))))
            added_imps = True
        if entry["ts"] > conv["ts"]:
            break
        text = entry["text"]
        for ip, letter in sorted(letters.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(ip, "IP %s" % letter)
        text = text.replace("IP IP ", "IP ")
        if entry.get("elsewhere"):
            text += " This is one of the household's own devices on someone else's Wi-Fi. One sighting only earns a probable link, and more days at home outvote it."
        rows.append((entry["ts"], entry["rule"], text))
    if imps and not added_imps:
        rows.append((imps[0]["ts"], "Campaign", "%d ad impressions served to this TV." % len(imps)))
    rows.sort(key=lambda r: r[0])
    conv_letter = letters.get(conv["ip"], "?")
    rows.append((conv["ts"], "Result",
                 "<strong>Conversion</strong> from IP %s, %d days after the last ad. "
                 "<strong>Raw IP: no match</strong>, because the ads were served to IP %s. "
                 "<strong>Household ID: matched</strong> to %s (%s link, %s)." % (
                     conv_letter, int(conv["gap_days"]), " and ".join(imp_ips), esc(story["resolved_id"]),
                     esc(conv["confidence"] or ""), esc(conv["how"] or ""))))
    log_rows = []
    for ts, rule, text in rows:
        safe = text if rule == "Result" else esc(text)
        log_rows.append([dates.day(ts), rule, safe])
    hl = (len(log_rows) - 1,)
    log_table = ('<div class="scroll"><table><thead><tr><th>Date</th><th>Rule</th><th>What the system saw and did</th></tr></thead><tbody>%s</tbody></table></div>'
                 % "".join('<tr%s><td class="rule">%s</td><td class="rule">%s</td><td>%s</td></tr>' % (
                     ' class="hl"' if i in hl else "", r[0], esc(r[1]), r[2]) for i, r in enumerate(log_rows)))
    n_moves = len(leases) - 1
    intro = ("<p class=\"sub\">Household <code>%s</code> in the answer key, which the system labeled <code>%s</code>. "
             "Its home IP changed %d time%s during the year. The top bar is what really happened; the second bar is the "
             "history the system rebuilt from sightings alone.</p>" % (
                 esc(story["true_id"]), esc(story["resolved_id"]), n_moves, "" if n_moves == 1 else "s"))
    return intro + '<div class="card">' + legend + '<div class="chart">' + "".join(svg) + "</div></div>" + \
        "<h3>The addresses</h3>" + key_table + "<h3>What the system did, step by step</h3>" + log_table


# ----------------------------------------------------------------- whole page
def build(cfg, main, alt, total_seconds):
    dates = Dates(cfg)
    A, A30 = main["attribution_all"], main["attribution_30"]
    hh, raw = A["hh"], A["raw"]
    c = main["counts"]
    det = main["detection"]
    ident = main["identity"]
    trk = main["tracking"]
    camp_len = int(cfg["campaign"]["length_days"])
    weeks_after = int(round(trk[-1]["since"] / 7.0)) if trk else 0
    P = []

    P.append('<p class="eyebrow">Concept prototype · simulated data</p>')
    P.append("<h1>Tracking households when the IP address keeps changing</h1>")
    P.append('<p class="lede"><strong>The question:</strong> how do you keep tracking the same households over a long '
             'period when their IP addresses change every so often?</p>')
    P.append('<p class="lede"><strong>The answer this prototype tests:</strong> stop treating the IP as the household. '
             'Give each household a stable ID, store every IP as a dated pointer to that ID, and move the pointer when '
             'something already tied to the household (its TV, a known browser, an email) shows up on a new address.</p>')
    P.append("<p>Everything below comes from one simulated year: %s households, %s IP changes, %s TV ad requests, %s ad "
             "impressions, %s site visits and %s conversions. Because the data is simulated, the true household behind "
             "every event is known, so both approaches can be scored against the right answer.</p>" % (
                 _n(c["households"]), _n(c["ip_changes"]), _n(c["tv_ad_requests"]), _n(c["impressions"]),
                 _n(c["site_visits"]), _n(c["conversions"])))

    # hero + tiles
    P.append('<section><div class="hero"><div class="card">'
             '<div class="tile"><div class="label"><span class="key"></span>Household ID</div>'
             '<div class="big">%s</div>'
             '<p style="margin-top:10px">of conversions from ad-exposed households were tied back to the right ad, '
             'however long ago it ran.</p>'
             '<div class="vs"><span class="key k2"></span><b>%s</b>with raw-IP matching, on the same events.</div>'
             '</div></div>' % (_p(hh["recall"]), _p(raw["recall"])))
    P.append('<div class="tiles">')
    P.append('<div class="card tile"><div class="label">Matches that pointed at the right household</div>'
             '<div class="value">%s</div><div class="delta">Raw IP: %s. Reused addresses credit the wrong home.</div></div>'
             % (_p(hh["precision"]), _p(raw["precision"])))
    if trk:
        P.append('<div class="card tile"><div class="label">Households still located correctly %d weeks after the campaign</div>'
                 '<div class="value">%s</div><div class="delta">The campaign\'s own IP list: %s.</div></div>'
                 % (weeks_after, _p(trk[-1]["hh"]), _p(trk[-1]["raw"])))
    P.append('<div class="card tile"><div class="label">Typical time to notice an IP change</div>'
             '<div class="value">%.1f days</div><div class="delta">%s of %s changes were picked up.</div></div>'
             % (det["median_lag_days"] or 0, _p(det["detected_pct"]), _n(det["changes"])))
    P.append("</div></div></section>")

    # chart 1
    bg = main["by_gap"]
    labels = ["%d–%d" % (b["lo"], b["hi"]) if b["hi"] else "%d+" % b["lo"] for b in bg]
    short = [str(b["lo"] // 30 + 1) + ("" if b["hi"] else "+") for b in bg]
    tips = ["%s days after the ad (%d conversions)" % (labels[i], b["n"]) for i, b in enumerate(bg)]
    home_n = sum(p["n"] for p in main["by_place"] if p["place"] == "At home")
    away_pct = 100.0 * (1 - home_n / float(max(1, sum(p["n"] for p in main["by_place"]))))
    P.append("<section><h2>The longer since the ad ran, the more raw-IP matching loses</h2>")
    P.append('<p class="sub">Share of conversions from ad-exposed households that each method correctly tied back to an '
             'impression, grouped by days since the household last saw the ad. The campaign ran for the first %d days; '
             'conversions happened all year. Hover or tap a point to see how many conversions sit behind it.</p>' % camp_len)
    P.append('<div class="card">' + line_chart(
        [(i, l) for i, l in enumerate(short)], tips,
        [("Household ID", [b["hh"] for b in bg]), ("Raw IP", [b["raw"] for b in bg])],
        "Months since the household last saw the ad (30-day blocks)",
        "Line chart: share of conversions correctly tied to an ad, by days since exposure, household ID versus raw IP.") + "</div>")
    if bg:
        P.append('<p class="takeaway">In the first 30 days raw IP ties back <strong>%s</strong> and household ID '
                 '<strong>%s</strong>. Past %d days it is <strong>%s</strong> against <strong>%s</strong>. Raw IP never '
                 'gets much above %s even at the start, because %s of these conversions happen away from the home '
                 'network.</p>' % (_p(bg[0]["raw"]), _p(bg[0]["hh"]), bg[-1]["lo"], _p(bg[-1]["raw"]), _p(bg[-1]["hh"]),
                                   _p(max(b["raw"] for b in bg)), _p(away_pct)))
    P.append("<details><summary>Show the numbers</summary>" + table(
        ["Days since ad", "Conversions", "Raw IP", "Household ID"],
        [[labels[i], _n(b["n"]), _p(b["raw"]), _p(b["hh"])] for i, b in enumerate(bg)], num_cols=(1, 2, 3)) + "</details></section>")

    # chart 2
    if trk:
        tips2 = ["Week %d after the campaign" % int(round(t["since"] / 7.0)) for t in trk]
        ticks2 = [(i, str(int(round(t["since"] / 7.0)))) for i, t in enumerate(trk) if int(round(t["since"] / 7.0)) % 4 == 0]
        P.append("<section><h2>A campaign's IP list goes stale. The household ID keeps up.</h2>")
        P.append('<p class="sub">Freeze the list of household IPs on the day the campaign ends, then check each week whether '
                 'each address still leads to the same home. The household ID is checked the same way, using only what '
                 'the system believed on that day.</p>')
        P.append('<div class="card">' + line_chart(
            ticks2, tips2,
            [("Household ID", [t["hh"] for t in trk]), ("Frozen IP list", [t["raw"] for t in trk])],
            "Weeks since the campaign ended",
            "Line chart: share of households whose current IP is known correctly, by weeks since the campaign ended.") + "</div>")
        P.append('<p class="takeaway">By week %d, <strong>%s</strong> of the frozen list no longer points at the right home, '
                 'and <strong>%s</strong> of it now points at a <em>different</em> household that was handed the old address. '
                 'The household ID holds at about <strong>%s</strong>; the remainder are homes that changed IP and have '
                 'not been seen again yet.</p>' % (weeks_after, _p(100 - trk[-1]["raw"]), _p(trk[-1]["raw_other"]), _p(trk[-1]["hh"])))
        P.append("<details><summary>Show the numbers</summary>" + table(
            ["Weeks since campaign", "Frozen IP list correct", "Frozen list points at another home", "Household ID correct",
             "Household ID out of date"],
            [[str(int(round(t["since"] / 7.0))), _p(t["raw"]), _p(t["raw_other"]), _p(t["hh"]), _p(t["hh_wrong"])]
             for t in trk[::4]], num_cols=(0, 1, 2, 3, 4)) + "</details></section>")

    # scorecard
    def rows_for(S):
        out = []
        for key, name in (("hh", "Household ID"), ("raw", "Raw IP")):
            m = S[key]
            out.append([name, _n(m["exposed"]), "%s (%s)" % (_n(m["correct"]), _p(m["recall"])), _n(m["missed"]),
                        _n(m["false_matches"]), _p(m["precision"])])
        return out
    heads = ["Method", "Conversions from exposed homes", "Tied back correctly", "Missed", "Credited to the wrong home",
             "Matches that were right"]
    P.append("<section><h2>Scorecard</h2>")
    P.append('<p class="sub">Every conversion checked against the answer key. "Credited to the wrong home" counts matches '
             'where the ad and the conversion actually belonged to different households.</p>')
    P.append("<h3>Looking back across the whole year</h3>" + table(heads, rows_for(A), num_cols=(1, 2, 3, 4, 5), highlight=(0,)))
    P.append("<h3>Looking back 30 days only</h3>" + table(heads, rows_for(A30), num_cols=(1, 2, 3, 4, 5), highlight=(0,)))
    P.append('<p class="takeaway">Inside a standard 30-day window raw IP does respectably (<strong>%s</strong>), because most '
             'home IPs have not changed yet. The case for a household ID is long windows and long-term reporting, which is '
             'exactly where the question points.</p>' % _p(A30["raw"]["recall"]))
    P.append('<div class="two"><div><h3>By where the person was when they converted</h3>' + table(
        ["Network", "Conversions", "Raw IP", "Household ID"],
        [[esc(p["place"]), _n(p["n"]), _p(p["raw"]), _p(p["hh"])] for p in main["by_place"]], num_cols=(1, 2, 3)) + "</div>")
    P.append("<div><h3>By how sure the system was</h3>" + table(
        ["Link confidence", "Matches made", "Right", "Share right"],
        [[t["level"].capitalize(), _n(t["credited"]), _n(t["right"]), _p(t["pct"]) if t["credited"] else "–"]
         for t in main["by_confidence"]], num_cols=(1, 2, 3)) +
        '<p class="takeaway">Every match carries a confidence level, so a report can be cut to confirmed links only.</p></div></div></section>')

    # story
    if main["story"]:
        P.append("<section><h2>One household, start to finish</h2>" + story_block(main["story"], dates, total_seconds) + "</section>")

    # rules
    rc = main["rule_counts"]
    used = {
        "R1": "%s households started" % _n(rc.get("R1", 0)),
        "R2": "%s address updates" % _n(rc.get("R2", 0)),
        "R3": "%s browsers linked, %s confirmed" % (_n(rc.get("R3", 0)), _n(rc.get("R3 confirmed", 0))),
        "R4": "%s email ties" % _n(rc.get("R4", 0)),
        "R5": _count(rc.get("R5", 0), "move"),
        "R6": "%s sightings ignored" % _n(rc.get("R6", 0)),
        "R7": "%s sightings held" % _n(rc.get("R7", 0)),
        "R8": _count(rc.get("R8", 0), "merge"),
    }
    P.append("<section><h2>The linking rules</h2>")
    P.append('<p class="sub">The system never works out a new IP from an old one. It recognizes a new IP when something it '
             'already trusts turns up there. These are all the rules it uses, and how often each fired in this run.</p>')
    P.append(table(["", "Rule", "What it does", "Confidence", "Used"],
                   [[rid, "<strong>%s</strong>" % esc(title), esc(desc), esc(conf), used.get(rid, "")]
                    for rid, title, desc, conf in RULES]))
    P.append('<p class="takeaway">Two jobs are being done here. The TV keeps the household\'s address current (R1, R2), because '
             'it never leaves the house and is seen often. Browsers and emails (R3, R4) connect what people do on the site '
             'back to the household, including when they are on mobile data or a new IP. R5 and R8 fired rarely in this run '
             'because the TV usually got there first.</p></section>')

    # misses
    n_hh_miss = sum(n for _, n in main["hh_misses"])
    n_raw_miss = sum(n for _, n in main["raw_misses"])
    P.append("<section><h2>What it still misses, and why</h2>")
    P.append('<p class="sub">The household ID did not connect %s of %s conversions from ad-exposed homes. Raw IP did not '
             'connect %s.</p>' % (_n(n_hh_miss), _n(hh["exposed"]), _n(n_raw_miss)))
    P.append('<div class="two"><div><h3>Household ID</h3>' + table(
        ["Reason", "Count"], [[esc(MISS_REASONS.get(k, k)), _n(n)] for k, n in main["hh_misses"]], num_cols=(1,)) + "</div>")
    P.append("<div><h3>Raw IP</h3>" + table(
        ["Reason", "Count"], [[esc(RAW_MISS_REASONS.get(k, k)), _n(n)] for k, n in main["raw_misses"]], num_cols=(1,)))
    P.append('<p class="takeaway">Raw IP also made %s wrong-home matches: %s where the address had been handed to another '
             'household, and %s where a guest converted on an exposed home\'s Wi-Fi.</p></div></div>' % (
                 _n(raw["false_matches"]), _n(main["raw_false_kinds"]["reassigned"]), _n(main["raw_false_kinds"]["guest"])))
    P.append('<p class="takeaway">Identity quality: %s real households became %s household IDs. %s were split in two, almost '
             'all because the TV\'s ad ID was reset (%s resets) and nothing else reconnected them. None were wrongly merged '
             'together%s.</p></section>' % (
                 _n(ident["true_households"]), _n(ident["resolved_households"]), _n(ident["split"]), _n(ident["tv_resets"]),
                 "" if ident["merged_wrong"] == 0 else " except %d" % ident["merged_wrong"]))

    # where you sit
    if alt:
        B = alt["attribution_all"]
        strict = sum(t["right"] for t in alt["by_confidence"] if t["level"] != "weak")
        P.append("<section><h2>This depends on a steady stream of sightings</h2>")
        P.append('<p class="sub">The results above assume the system sits where a CTV platform sits and sees each TV\'s ad '
                 'requests all year. The same simulated year was run again with an advertiser-only view: the TV is seen '
                 'only when it is served one of the campaign\'s ads, and after that the only signal is the site pixel.</p>')
        P.append(table(
            ["View", "Raw IP tied back", "Household ID tied back", "Household ID matches that were right",
             "Households located at year end"],
            [["<strong>Platform view</strong><br>TV ad requests seen all year", _p(raw["recall"]), _p(hh["recall"]),
              _p(hh["precision"]), _p(trk[-1]["hh"]) if trk else "–"],
             ["<strong>Advertiser-only view</strong><br>TV seen only during the campaign", _p(B["raw"]["recall"]),
              _p(B["hh"]["recall"]), _p(B["hh"]["precision"]), _p(alt["tracking"][-1]["hh"]) if alt["tracking"] else "–"]],
            num_cols=(1, 2, 3, 4)))
        P.append('<p class="takeaway">With the thinner feed the household ID still beats raw IP (<strong>%s</strong> against '
                 '<strong>%s</strong>), because cookies and emails keep working when the IP changes. But most of those links '
                 'are weak, and only %s of the %s correct matches come from confirmed or probable links. A household ID is only as '
                 'current as the sightings feeding it. In practice that means either sitting on the platform\'s data, '
                 'buying an identity graph, or capturing an email or phone number on every form, booking and call.</p></section>'
                 % (_p(B["hh"]["recall"]), _p(B["raw"]["recall"]), _n(strict), _n(B["hh"]["correct"])))

    # assumptions
    P.append("<section><h2>What is simulated and what is left out</h2><ul>")
    for item in (
        "All data is invented. IP addresses come from ranges reserved for testing, and the hashed emails are hashes of made-up addresses.",
        "No ad effect is modeled. This tests whether an exposure and a conversion can be connected, not whether the ad caused the conversion.",
        "How often home IPs change, and how often a freed address is handed to another household, are assumptions set in <code>config.json</code>. Change them and rerun to see how sensitive the result is.",
        "The home / mobile / business IP-type lookup is assumed to be correct. Real lookups mislabel some small-business and home-office lines.",
        "Left out: TVs with ad tracking limited, homes with several TVs, phone numbers, postal addresses and CRM IDs, VPNs and Apple Private Relay, and IPv6 privacy addresses.",
        "Consent is not modeled. A real version has to honor opt-outs and treat IPs, device IDs and hashed emails as personal information under state privacy laws.",
    ):
        P.append("<li>%s</li>" % item)
    P.append("</ul><details><summary>Settings used for this run</summary><pre>%s</pre></details></section>" % esc(json.dumps(cfg, indent=2)))
    P.append("<footer>Generated by <code>python3 run.py</code>. Same settings and seed always produce the same report.</footer>")

    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Household ID Prototype</title><style>%s</style></head><body><main>%s</main><script>%s</script></body></html>"
            % (CSS, "\n".join(P), JS))
