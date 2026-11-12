"""Which resorts to check this run, kept inside the Apify budget (called by run.py every hour).

Cadence (each resort's tier comes from roster.py):
  weekly     Meta + Google every week, from Monday 12:00 UTC (any collection day once 8+ days old)
  biweekly   Meta + Google every 2 weeks, on any collection day (Mon/Tue/Thu/Fri)
  Google for a resort where the atlas found no Google ads: every 8 weeks, in case they start
Each run takes the weekly resorts first, then the most overdue, then resorts never checked (best
prospects first), up to MAX_JOBS Apify jobs; the next hourly run carries on.

Budget: a job only starts if this month's Apify spend plus the job's likely cost stays under
APIFY_MONTHLY_BUDGET (default $18, for the $19 plan) and under the Apify account's own monthly limit.
Whatever doesn't fit waits for the next month, weekly resorts first. A resort's first check only pulls
Google ads shown in the last FIRST_DAYS days (max FIRST_GOOGLE) to keep the start-up cost down.
A job that fails is skipped for the rest of the day (data/collect_fails.json) so it can't eat the budget.
"""
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

import collect
import library
import roster

BUDGET = float(os.environ.get("APIFY_MONTHLY_BUDGET") or 18)
MAX_JOBS = int(os.environ.get("MAX_JOBS_PER_RUN") or 60)
BIWEEKLY, NO_GOOGLE_EVERY = 14, 56
FIRST_DAYS, FIRST_GOOGLE, GOOGLE_CAP, META_CAP = 120, 30, 50, 150
EST = {"meta": 0.03, "google": 0.06, "google_first": 0.07}  # a job's likely worst cost, for the budget check
FAILS = os.path.join(library.DATA, "collect_fails.json")


def month_spend(today):
    m, tot = today.strftime("%Y-%m"), 0.0
    try:
        with open(os.path.join(library.DATA, "runs.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("started") or "")[:7] == m and r.get("status") != "REUSED":
                    tot += float(r.get("cost_usd") or 0)
    except (FileNotFoundError, ValueError):
        pass
    return tot


def apify_limits(token):
    """(monthly limit, used this billing cycle) from the Apify account, or (None, None)."""
    try:
        d = requests.get(f"{collect.API}/users/me/limits", params={"token": token}, timeout=30).json()["data"]
        return float(d["limits"]["maxMonthlyUsageUsd"]), float(d["current"]["monthlyUsageUsd"])
    except Exception as e:
        print("  Apify limits not read:", str(e)[:120])
        return None, None


def last_checks():
    last = {}
    for p in ("meta", "google"):
        for d, slug, _ in library.raw_files(p):
            if d > last.get((p, slug), ""):
                last[(p, slug)] = d
    return last


def due(now, platforms=("meta", "google"), force=False):
    """[(priority, platform, resort, last check date or None)] due now, most important first."""
    today, last, jobs = now.date(), last_checks(), []
    monday = today.weekday() == 0 and now.hour >= 12
    for r in roster.load():
        weekly = r.get("tier") == "weekly"
        rank = roster.num(r.get("atlas_rank")) or 999
        for p in platforms:
            if not (r.get("meta_page_id") if p == "meta" else r.get("domain")):
                continue
            d = last.get((p, r["slug"]))
            age = (today - date.fromisoformat(d)).days if d else 999
            if p == "google" and r.get("google_known") == "no":
                ok = age >= NO_GOOGLE_EVERY
            elif weekly:
                ok = (force and age >= 1) or (monday and age >= 5) or age >= 8
            else:
                ok = age >= BIWEEKLY - 1
            if ok:
                jobs.append(((0 if weekly else 1, 0 if d else 1, -age if d else rank), p, r, d))
    jobs.sort(key=lambda j: j[0])
    return jobs


def mark(st, now, platforms, fails):
    """The Monday report waits (st meta_last / google_last) until every weekly resort is checked."""
    if now.weekday() == 0 and now.hour < 12:
        return
    left = [j for j in due(now, platforms) if j[2].get("tier") == "weekly" and f"{j[1]}:{j[2]['slug']}" not in fails]
    for p in platforms:
        if not any(j[1] == p for j in left):
            st[f"{p}_last"] = now.date().isoformat()


def run(st, now, platforms=("meta", "google"), force=False):
    """Collect whatever is due, within budget. force: re-check the weekly resorts now (manual runs)."""
    today = now.date().isoformat()
    fails = {k: v for k, v in library.load_json(FAILS, {}).items() if v == today}
    jobs = [j for j in due(now, platforms, force) if f"{j[1]}:{j[2]['slug']}" not in fails]
    if not jobs:
        print("No collection due")
        return mark(st, now, platforms, fails)
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("APIFY_TOKEN is not set - no collection")
        return
    cap, used = apify_limits(token)
    budget = min(BUDGET, cap) if cap else BUDGET
    spent = max(month_spend(now.date()), used or 0)
    left, picked = budget - spent, []
    for _, p, r, d in jobs:
        est = EST["google_first" if p == "google" and not d else p]
        if len(picked) < MAX_JOBS and est <= left:
            left -= est
            picked.append((p, r, d))
    wait = len(jobs) - len(picked)
    print(f"Collection: {len(jobs)} jobs due ({sum(j[2].get('tier') == 'weekly' for j in jobs)} weekly), running {len(picked)}; "
          f"Apify ${spent:.2f} used of ${budget:.2f} this month" + (f"; {wait} wait for the next run / month" if wait else ""))
    if not picked:
        return mark(st, now, platforms, fails)

    def work(job):
        p, r, d = job
        label = f"{p}:{r['slug']}"
        if p == "meta":
            actor, payload = collect.META_ACTOR, collect.meta_input(r, META_CAP)
        else:
            since = (date.fromisoformat(d) - timedelta(days=3)) if d else (now.date() - timedelta(days=FIRST_DAYS))
            actor, payload = collect.GOOGLE_ACTOR, collect.google_input(r, GOOGLE_CAP if d else FIRST_GOOGLE, since.isoformat())
        try:
            items, info = collect.run_actor(actor, payload, token, label)
        except Exception as e:
            print(f"  {label} failed: {str(e)[:200]}")
            fails[label] = today
            return {"label": label, "actor": actor, "status": "ERROR", "items": 0, "cost_usd": 0,
                    "run_id": "", "started": "", "finished": ""}
        if info["status"] == "SUCCEEDED":
            collect.save_raw(p, r["slug"], items, today)
        else:  # half-finished: don't save it (it would end ads that are still running); retry tomorrow
            fails[label] = today
        return info

    with ThreadPoolExecutor(max_workers=3) as ex:
        infos = list(ex.map(work, picked))
    collect.append_runs(infos)
    library.save_json(FAILS, fails, indent=1)
    cost = sum(float(i["cost_usd"] or 0) for i in infos)
    print(f"Collected {sum(i['items'] for i in infos)} ads in {len(infos)} jobs, Apify ${cost:.2f}, "
          f"{sum(i['status'] != 'SUCCEEDED' for i in infos)} failed")
    mark(st, now, platforms, fails)
