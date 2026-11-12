"""Weekly ad report: what the pilot resorts launched, stopped, and kept running, with an AI strategist
summary. Saved to the site (docs/reports/<date>.html) and emailed.

Run:  python report.py --preview out.html   (build without AI or email, write the email HTML to a file)
      python report.py --send               (full report now: AI summary, site page, email)
Normally run.py decides when to send (Mondays, after the morning collection).
"""
import argparse
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape

import ai
import library
import mailer

SITE_URL = os.environ.get("SITE_URL", "https://deanisaac06.github.io/Ski-Area-Ad-Tracking/")
REPORTS = os.path.join(library.DOCS, "reports")
INDEX = os.path.join(REPORTS, "index.json")
MAX_NEW_CARDS, MAX_TOP_CARDS = 24, 12

PROMPT = """Below is this week's activity in the paid ads of {n_resorts} US and Canadian ski resorts we track (Meta = Facebook/Instagram ads, Google = Search/YouTube/Display ads from Google's Ads Transparency Center). Week: {since} to {today}.

Numbers: {n_new} new ads launched ({n_new_meta} Meta, {n_new_google} Google). {n_ended} ads stopped. {n_live_meta} Meta ads are live right now.
Campaign mix of new ads: {mix}.
Most new ads: {busiest}.

NEW ADS (resort | platform | format | campaign | offer/prices/deadline | copy):
{new_rows}

LONGEST-RUNNING / TOP-SCORING LIVE ADS (winner score = budget-adjusted: outlasting its launch batch, run length vs the resort's own ads (weighted down for resorts that leave everything running), extra versions, steady serving, reused creative; a proxy, since spend and results aren't public):
{top_rows}

ADS THAT STOPPED THIS WEEK:
{ended_rows}

Write two short paragraphs (120-180 words total) for a marketer who runs a ski resort's ads:
1) What resorts are pushing right now and why it matters for this point in the season: the dominant offers, deadlines and price points, who launched a big batch (a creative test or a push), anything a resort stopped early.
2) The strategic read: what the longest-running ads have in common (format, message, offer type), anything markedly different worth stealing, and one concrete thing to watch or do next week.
Name resorts and specific offers/prices. Don't repeat the raw numbers back. No headings, no bullet points."""


def fmt_day(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d") if d else "-"


def gather(out, now, since=None):
    today = now.date().isoformat()
    reports = library.load_json(INDEX, [])
    since = since or (max(r["date"] for r in reports) if reports else (now.date() - timedelta(days=7)).isoformat())
    new = [a for a in out if (a.get("start") or "") >= since]
    ended = [a for a in out if not a["live"] and (a.get("end") or "") >= since]
    live = [a for a in out if a["live"]]
    # this season's campaigns only - Google's always-on brand/Maps ads (running for years) would crowd everything else out
    recent = (now.date() - timedelta(days=180)).isoformat()
    top = sorted([a for a in live if a.get("ws") is not None and (a.get("start") or "") >= recent],
                 key=lambda a: (-a["ws"], -a["days"]))[:MAX_TOP_CARDS]
    by_resort = {}
    for a in out:
        r = by_resort.setdefault(a["n"], Counter())
        r["meta_live"] += a["p"] == "meta" and a["live"]
        r["google_live"] += a["p"] == "google" and a["live"]
        r["new"] += a in new
        r["ended"] += a in ended
    mix = Counter(c for a in new for c in a["camp"][:1])
    return {"since": since, "today": today, "new": sorted(new, key=lambda a: (a["n"], a["p"])), "ended": ended,
            "live": live, "top": top, "by_resort": by_resort, "mix": mix,
            "standouts": [a for a in new + top if a.get("stand")][:6],
            "offers": [a for a in new if a.get("offer") or a.get("prices") or a.get("deadline")]}


def row(a):
    offer = "; ".join(x for x in [a.get("offer", ""), " ".join(a.get("prices", [])),
                                  f"deadline {a['deadline']}" if a.get("deadline") else ""] if x)
    copy = (a.get("title", "") + " - " + (a.get("body") or a.get("seen_text") or ""))[:220].replace("\n", " ")
    return f"{a['n']} | {a['p']} | {a['kind']} | {', '.join(a['camp'])} | {offer or '-'} | {copy}"


def ai_prompt(g):
    busiest = Counter(a["n"] for a in g["new"]).most_common(4)
    new_rows = g["new"]
    if len(new_rows) > 120:                 # keep the prompt a sensible size: copy-bearing ads first
        new_rows = sorted(new_rows, key=lambda a: -len(a.get("body", "") + a.get("title", "")))[:120]
    return PROMPT.format(
        n_resorts=len(g["by_resort"]), since=g["since"], today=g["today"], n_new=len(g["new"]),
        n_new_meta=sum(a["p"] == "meta" for a in g["new"]), n_new_google=sum(a["p"] == "google" for a in g["new"]),
        n_ended=len(g["ended"]), n_live_meta=sum(a["p"] == "meta" for a in g["live"]),
        mix=", ".join(f"{c} {n}" for c, n in g["mix"].most_common()) or "none",
        busiest=", ".join(f"{n} ({c})" for n, c in busiest) or "none",
        new_rows="\n".join(row(a) for a in new_rows) or "(none)",
        top_rows="\n".join(f"score {a['ws']}, {a['days']}d live: " + row(a) for a in g["top"]) or "(none)",
        ended_rows="\n".join(f"{a['days']}d: " + row(a) for a in g["ended"][:40]) or "(none)")


# ------------------------------------------------------------------ html
PLAT = {"meta": ("Meta", "#1D5C96"), "google": ("Google", "#2E7D4F")}


def score_chip(a):
    if a.get("ws") is None:
        return "<span style='color:#888;font-size:11px'>too early</span>"
    col = "#2E7D4F" if a["ws"] >= 70 else "#1D5C96" if a["ws"] >= 45 else "#888"
    return f"<span style='background:{col};color:#fff;border-radius:3px;padding:0 5px;font-size:11px'>{a['ws']}</span>"


def card(a, img):
    name, col = PLAT[a["p"]]
    pic = (f"<img src='{img}' width='170' style='display:block;width:170px;max-width:100%;border-radius:4px;border:1px solid #e3e7ec'>"
           if img else
           f"<div style='width:170px;height:120px;background:#eef2f6;border-radius:4px;color:#456;font-size:12px;padding:10px;box-sizing:border-box'>"
           f"{escape((a.get('title') or a.get('seen_text') or a['kind'])[:90])}</div>")
    line = a.get("offer") or a.get("title") or a.get("seen_text") or ""
    return (f"<td valign='top' style='padding:6px;width:33%'>"
            f"<a href='{escape(a.get('url') or SITE_URL)}' style='text-decoration:none;color:#13212E'>{pic}</a>"
            f"<div style='font:600 13px/1.3 Arial,sans-serif;margin-top:5px'>{escape(a['n'])}</div>"
            f"<div style='font:11px Arial,sans-serif;color:#5B6B7B'><span style='color:{col};font-weight:600'>{name}</span> &middot; "
            f"{escape(a['kind'])} &middot; {escape(a['camp'][0])}</div>"
            f"<div style='font:12px/1.35 Arial,sans-serif;color:#333;margin-top:2px'>{escape(line[:90])}</div>"
            f"<div style='font:11px Arial,sans-serif;color:#5B6B7B;margin-top:2px'>{fmt_day(a.get('start'))} &middot; "
            f"{a['days']}d {'live' if a['live'] else 'ran'} &middot; {score_chip(a)}</div></td>")


def grid(ads, img_for):
    rows = []
    for i in range(0, len(ads), 3):
        cells = "".join(card(a, img_for(a)) for a in ads[i:i + 3])
        rows.append(f"<tr>{cells}{'<td></td>' * (3 - len(ads[i:i + 3]))}</tr>")
    return f"<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>{''.join(rows)}</table>"


def h2(t):
    return f"<h2 style='font:700 17px Arial,sans-serif;text-transform:uppercase;letter-spacing:.03em;margin:26px 0 8px;color:#13212E'>{t}</h2>"


def render(g, summary, img_for, notice=None, for_site=False):
    n_meta = sum(a["p"] == "meta" for a in g["new"])
    n_google = len(g["new"]) - n_meta
    stats = [("New ads", len(g["new"]), f"{n_meta} Meta &middot; {n_google} Google"),
             ("Stopped", len(g["ended"]), "this week"),
             ("Live on Meta", sum(a["p"] == "meta" for a in g["live"]), "right now"),
             ("Resorts", len(g["by_resort"]), "tracked")]
    stat_html = "".join(f"<td style='padding:10px 12px;background:#fff;border:1px solid #DAE1E8'>"
                        f"<div style='font:10px Arial,sans-serif;text-transform:uppercase;letter-spacing:.06em;color:#5B6B7B'>{k}</div>"
                        f"<div style='font:700 24px Arial,sans-serif;color:#13212E'>{v}</div>"
                        f"<div style='font:11px Arial,sans-serif;color:#5B6B7B'>{s}</div></td>" for k, v, s in stats)
    mix = " &middot; ".join(f"{escape(c)} <b>{n}</b>" for c, n in g["mix"].most_common()) or "No new ads"
    offers = "".join(f"<tr><td style='padding:5px 8px;border-bottom:1px solid #eee;font:600 13px Arial'>{escape(a['n'])}</td>"
                     f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font:13px Arial'>{escape(a.get('offer') or a.get('title') or '')}</td>"
                     f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font:12px Arial;color:#555;white-space:nowrap'>{escape(' '.join(a.get('prices', [])))}"
                     f"{(' &middot; by ' + fmt_day(a['deadline'])) if a.get('deadline') else ''}</td></tr>"
                     for a in sorted(g["offers"], key=lambda a: a["n"])[:30])
    resorts = "".join(f"<tr><td style='padding:4px 8px;border-bottom:1px solid #eee;font:13px Arial'>{escape(n)}</td>"
                      + "".join(f"<td style='padding:4px 8px;border-bottom:1px solid #eee;font:13px Arial;text-align:right'>{c[k] or '&ndash;'}</td>"
                                for k in ("new", "ended", "meta_live", "google_live")) + "</tr>"
                      for n, c in sorted(((n, c) for n, c in g["by_resort"].items() if c["new"] or c["ended"]),
                           key=lambda x: (-x[1]["new"], -x[1]["ended"], x[0]))[:40])  # only resorts with changes
    stand = "".join(f"<li style='margin:4px 0'><b>{escape(a['n'])}</b> ({PLAT[a['p']][0]}): {escape(a['stand'])}</li>" for a in g["standouts"])
    new_cards = sorted(g["new"], key=lambda a: (not img_for(a), -(a.get("versions") or 1)))[:MAX_NEW_CARDS]
    paras = "".join(f"<p style='margin:0 0 10px'>{escape(p.strip())}</p>" for p in (summary or "").split("\n") if p.strip())
    note = (f"<div style='background:#FBF0DC;color:#7a4b0b;padding:10px 12px;border-radius:6px;font:13px Arial;margin-bottom:14px'>{escape(notice)}</div>"
            if notice else "")
    more_new = (f"<p style='font:13px Arial;color:#5B6B7B'>+ {len(g['new']) - len(new_cards)} more new ads on the "
                f"<a href='{SITE_URL}'>ad library site</a>.</p>") if len(g["new"]) > len(new_cards) else ""
    head = "" if for_site else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resort ads weekly - {fmt_day(g['today'])}</title></head>
<body style="margin:0;background:#F3F5F8;color:#13212E">{head}
<div style="max-width:680px;margin:0 auto;padding:18px 14px 40px;font:14px/1.5 Arial,sans-serif">
<div style="font:700 24px Arial;text-transform:uppercase;letter-spacing:.02em">Resort ads weekly</div>
<div style="color:#5B6B7B;font-size:13px;margin-bottom:14px">{fmt_day(g['since'])} &ndash; {fmt_day(g['today'])} &middot; {len(g['by_resort'])} resorts &middot;
<a href="{SITE_URL}">open the ad library</a></div>
{note}
<table width="100%" cellspacing="6" style="border-collapse:separate;margin:0 -6px"><tr>{stat_html}</tr></table>
{('<div style="background:#fff;border:1px solid #DAE1E8;border-radius:8px;padding:14px 16px;margin-top:12px">' + paras + '</div>') if paras else ''}
{h2('New this week')}
<div style="font-size:13px;color:#5B6B7B;margin-bottom:6px">{mix}</div>
{grid(new_cards, img_for) if new_cards else '<p style="color:#5B6B7B">No new ads launched this week.</p>'}
{more_new}
{(h2('Offers & deadlines') + '<table width="100%" style="border-collapse:collapse;background:#fff">' + offers + '</table>') if offers else ''}
{h2('Top-scoring live ads this season')}
<div style="font-size:12px;color:#5B6B7B;margin-bottom:6px">Winner score 0&ndash;100: adjusted for budget. Whether an ad outlasted the others its resort launched the same week, how long it ran vs that resort's own ads, extra versions, steady serving and reuse. Resorts keep paying for what works.</div>
{grid(g['top'], img_for) if g['top'] else '<p style="color:#5B6B7B">Not enough history yet.</p>'}
{(h2('Stands out') + '<ul style="padding-left:18px;margin:0">' + stand + '</ul>') if stand else ''}
{h2('Resorts with changes this week')}
<table width="100%" style="border-collapse:collapse;background:#fff"><tr style="background:#E8EDF2">
<th style="padding:5px 8px;text-align:left;font:10px Arial;text-transform:uppercase">Resort</th><th style="padding:5px 8px;text-align:right;font:10px Arial;text-transform:uppercase">New</th>
<th style="padding:5px 8px;text-align:right;font:10px Arial;text-transform:uppercase">Stopped</th><th style="padding:5px 8px;text-align:right;font:10px Arial;text-transform:uppercase">Meta live</th>
<th style="padding:5px 8px;text-align:right;font:10px Arial;text-transform:uppercase">Google live</th></tr>{resorts}</table>
<p style="font-size:12px;color:#888;margin-top:22px">Meta shows US ads only while they run, so Meta history starts Nov 10, 2026. Google history goes back years.
Scores are estimates from behaviour; neither platform publishes spend or results.</p>
</div></body></html>"""


def text_version(g, summary):
    lines = [f"Resort ads weekly {g['since']} to {g['today']}", "", summary or "", "",
             f"New ads: {len(g['new'])}  Stopped: {len(g['ended'])}", ""]
    lines += [f"- {row(a)}" for a in g["new"][:40]]
    lines += ["", f"Full library: {SITE_URL}"]
    return "\n".join(lines)


# ------------------------------------------------------------------ publish
def site_img(a):
    return f"../{a['img']}" if a.get("img") else ""


def publish(g, summary, notice=None, send=True):
    os.makedirs(REPORTS, exist_ok=True)
    page = render(g, summary, site_img, notice, for_site=True)
    with open(os.path.join(REPORTS, f"{g['today']}.html"), "w", encoding="utf-8") as f:
        f.write(page)
    idx = [r for r in library.load_json(INDEX, []) if r["date"] != g["today"]]
    idx.append({"date": g["today"], "since": g["since"], "file": f"reports/{g['today']}.html",
                "new": len(g["new"]), "ended": len(g["ended"]), "ai": bool(summary)})
    library.save_json(INDEX, sorted(idx, key=lambda r: r["date"]), indent=1)
    sent = False
    if send:
        images = {}

        def cid(a):
            if not a.get("img"):
                return ""
            k = "a" + a["key"]
            if k not in images:
                try:
                    with open(os.path.join(library.DOCS, a["img"]), "rb") as f:
                        images[k] = f.read()
                except OSError:
                    return ""
            return f"cid:{k}"

        html = render(g, summary, cid, notice)
        subject = f"Resort ads weekly: {len(g['new'])} new, {len(g['ended'])} stopped ({fmt_day(g['today'])})"
        sent = mailer.send_email(subject, text_version(g, summary), html=html, images=images,
                                 to=os.environ.get("REPORT_TO") or os.environ.get("ALERT_TO"))
    print(f"Report {g['today']}: {len(g['new'])} new, {len(g['ended'])} stopped, AI summary {'yes' if summary else 'no'}, "
          f"emailed {'yes' if sent else 'no'}")
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", help="write the email HTML (site image paths) to this file; no AI, no email")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--since")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    _, out = library.build(now)
    g = gather(out, now, args.since)
    if args.preview:
        with open(args.preview, "w", encoding="utf-8") as f:
            f.write(render(g, "(AI summary appears here)", lambda a: a["img"] if a.get("img") else ""))
        print("wrote", args.preview, "-", len(g["new"]), "new ads")
        return
    summary = ai.summarize(ai_prompt(g))
    publish(g, summary, None if summary else "The AI summary couldn't be written this week.", send=args.send)
    library.build(now)                      # refresh the site's report list


if __name__ == "__main__":
    main()
