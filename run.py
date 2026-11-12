"""The weekly routine, run every hour on collection/report days by .github/workflows/weekly.yml.
Each run works out what's due and does only that, so a late or skipped GitHub run just catches up:

  Meta collection     Mondays and Thursdays (from 12:00 UTC); also if 5+ days have passed
  Google collection   Mondays (from 12:00 UTC); also if 8+ days have passed. Only ads shown since the
                      last check, so it's cheap.
  Images              every run, for any ad without a saved image (Meta links expire in ~5 days)
  AI tags             every run, up to 60 Gemini calls, newest ads first
  Weekly report       Mondays from 14:00 UTC (~6-7am Pacific), after Monday's collection. If the AI summary
                      fails it tries again every hour; after 24 hours it sends without it, with a note.
  Site data           rebuilt at the end of every run

State lives in data/status.json.
Run:  python run.py --auto | --collect | --report | --build
"""
import argparse
from datetime import date, datetime, timedelta, timezone

import ai
import collect
import library
import media
import report

STATUS = library.os.path.join(library.DATA, "status.json")
META_DAYS, GOOGLE_DAYS = (0, 3), (0,)        # Monday, Thursday / Monday
COLLECT_HOUR, REPORT_HOUR = 12, 14
AI_WAIT_HOURS = 24


def days_since(d, today):
    return (today - date.fromisoformat(d)).days if d else 999


def due_collections(st, now):
    today = now.date()
    due = []
    m, g = days_since(st.get("meta_last"), today), days_since(st.get("google_last"), today)
    if (today.weekday() in META_DAYS and now.hour >= COLLECT_HOUR and m >= 2) or m >= 5:
        due.append("meta")
    if (today.weekday() in GOOGLE_DAYS and now.hour >= COLLECT_HOUR and g >= 5) or g >= 8:
        due.append("google")
    return due


def do_collect(st, platforms, now):
    today = now.date().isoformat()
    since = None
    if "google" in platforms:
        last = st.get("google_last") or (now.date() - timedelta(days=30)).isoformat()
        since = (date.fromisoformat(last) - timedelta(days=3)).isoformat()   # small overlap
    collect.collect(tuple(platforms), google_since=since)
    for p in platforms:
        st[f"{p}_last"] = today
    library.save_json(STATUS, st, indent=1)


def report_due(st, now):
    """This Monday's report, once Monday's collection is in. Returns the week's Monday (YYYY-MM-DD) or None."""
    monday = (now.date() - timedelta(days=now.weekday())).isoformat()
    if st.get("report_week") == monday:
        return None
    if now.date().isoformat() == monday and now.hour < REPORT_HOUR:
        return None
    if (st.get("meta_last") or "") < monday or (st.get("google_last") or "") < monday:
        return None                                    # Monday's collections haven't happened yet
    if now.weekday() > 1 and monday not in st.get("report_first_try", {}):
        return None                                    # missed Mon/Tue entirely - wait for next week
    return monday


def do_report(st, now, week, force_send=False):
    _, out = library.build(now)
    g = report.gather(out, now)
    summary = ai.summarize(report.ai_prompt(g))
    first_try = st.setdefault("report_first_try", {}).setdefault(week, now.isoformat())
    waited = (now - datetime.fromisoformat(first_try)).total_seconds() / 3600
    if not summary and not force_send and waited < AI_WAIT_HOURS:
        print(f"AI summary failed - holding the report and retrying next hour ({waited:.0f}h of {AI_WAIT_HOURS}h)")
        library.save_json(STATUS, st, indent=1)
        return False
    notice = None if summary else ("The AI summary is broken this week (Gemini didn't answer for 24 hours), "
                                   "so this report has the data only.")
    report.publish(g, summary, notice)
    st["report_week"] = week
    st["report_sent"] = now.isoformat()
    st["report_first_try"] = {}
    library.save_json(STATUS, st, indent=1)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="do whatever is due (the hourly job)")
    ap.add_argument("--collect", choices=["meta", "google", "both"], help="collect now")
    ap.add_argument("--report", action="store_true", help="build and send the report now")
    ap.add_argument("--build", action="store_true", help="just save images, tag and rebuild the site")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    st = library.load_json(STATUS, {})

    platforms = []
    if args.collect:
        platforms = ["meta", "google"] if args.collect == "both" else [args.collect]
    elif args.auto:
        platforms = ["meta", "google"]  # cadence.py decides which resorts are due
    if platforms:
        try:  # each resort weekly or every 2 weeks, inside the monthly Apify budget (cadence.py)
            __import__("cadence").run(st, now, tuple(platforms), force=bool(args.collect))
        except Exception as e:
            print("Collection failed:", str(e)[:300])
        library.save_json(STATUS, st, indent=1)
    else:
        print("No collection due")

    media.run()                      # before tagging: image-only ads are tagged from their saved image
    ai.tag_new_ads(); __import__("archive").run()  # frames, every card/version, AI video notes, landing pages

    try:
        __import__("quality").run()  # ad health check: repair broken ads or set them aside as unavailable
    except Exception as e:
        print("Ad health check skipped:", str(e)[:200])

    if args.report:
        do_report(st, now, (now.date() - timedelta(days=now.weekday())).isoformat(), force_send=True)
    elif args.auto:
        week = report_due(st, now)
        if week:
            do_report(st, now, week)
    library.build(now)


if __name__ == "__main__":
    main()
