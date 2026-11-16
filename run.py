"""The weekly routine, run every hour on collection/report days by .github/workflows/weekly.yml.
Each run works out what's due and does only that, so a late or skipped GitHub run just catches up:

  Meta collection     Mondays and Thursdays (from 12:00 UTC); also if 5+ days have passed
  Google collection   Mondays (from 12:00 UTC); also if 8+ days have passed. Only ads shown since the
                      last check, so it's cheap.
  Images              every run, for any ad without a saved image (Meta links expire in ~5 days)
  AI tags             every run, up to 60 AI calls, newest ads first (Gemini; Groq/Cloudflare while it's busy)
  Catch-up            when a run leaves AI tags or video notes waiting and made progress, it starts a "tag" run
                      (no collection, up to 200 AI calls) straight after - see data/backlog.json
  Weekly report       Mondays from 14:00 UTC (~6-7am Pacific), after Monday's collection. If the AI summary
                      fails it tries again every hour; after 24 hours it sends without it, with a note.
  Site data           rebuilt at the end of every run

State lives in data/status.json.
Run:  python run.py --auto | --collect | --report | --build | --tag
"""
import argparse
import json
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
    try:
        report.publish(g, summary, notice)
    except Exception as e:  # e.g. Gmail dropping the login - the report page is saved; retry the email next run
        library.save_json(STATUS, st, indent=1)
        if waited < AI_WAIT_HOURS:
            print(f"Report email failed ({str(e)[:160]}) - the page is saved in docs/reports; retrying next run "
                  f"({waited:.0f}h of {AI_WAIT_HOURS}h)")
            return False
        print(f"Report email still failing after {AI_WAIT_HOURS}h ({str(e)[:160]}) - giving up for this week; "
              "the report is on the site under docs/reports")
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
    ap.add_argument("--tag", action="store_true", help="catch-up: no collection, a long AI tagging session, then rebuild")
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
    arch = __import__("archive")
    if args.tag:                     # catch-up run: most of the job's time goes to the AI backlog
        tagged = ai.tag_new_ads(max_calls=200, max_seconds=3600)
        arch.run(max_seconds=1800, note_calls=60)
    else:
        tagged = ai.tag_new_ads()
        arch.run()                   # frames, every card/version, AI video notes, landing pages
    try:
        left = ai.tag_backlog()
        notes = arch.NOTES
        more = (left > 0 and tagged >= 5) or (notes["left"] > 0 and notes["done"] >= 3)
        library.save_json(library.os.path.join(library.DATA, "backlog.json"),
                          {"checked": now.isoformat(timespec="minutes"), "tags_left": left, "tagged_this_run": tagged,
                           "video_notes_left": notes["left"], "video_notes_this_run": notes["done"],
                           "catch_up": more, "run_id": library.os.environ.get("GITHUB_RUN_ID", "")}, indent=1)
        print(f"Backlog: {left} ads waiting for AI tags, {notes['left']} videos waiting for notes"
              + (" - starting a catch-up run next" if more else ""))
    except Exception as e:
        print("Backlog check failed:", str(e)[:200])

    try:
        __import__("quality").run()  # ad health check: repair broken ads or set them aside as unavailable
    except Exception as e:
        print("Ad health check skipped:", str(e)[:200])

    try:
        __import__("r2").run()  # saved videos -> Cloudflare R2, so they don't fill up GitHub
    except Exception as e:
        print("R2 step skipped:", str(e)[:200])

    if args.report:
        do_report(st, now, (now.date() - timedelta(days=now.weekday())).isoformat(), force_send=True)
    elif args.auto or args.tag:
        week = report_due(st, now)
        if week:
            try:
                do_report(st, now, week)
            except Exception as e:  # never let the report stop the site rebuild or the AI catch-up
                print("Report failed:", str(e)[:300])
    library.build(now)


if __name__ == "__main__":
    main()
