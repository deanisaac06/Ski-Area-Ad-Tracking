"""Which resorts to check this run, kept inside the Apify budget (called by run.py every hour).

Cadence (each resort's group comes from roster.py; days between checks in GROUPS below):
  prospect   Meta weekly (from Monday 12:00 UTC), Google every 2 weeks
  benchmark  Meta every 2 weeks, Google every 4 weeks
  mid        Meta every 2 weeks, Google every 6 weeks
  low        Meta every 4 weeks, Google every 12 weeks
  Google for a resort where the atlas found no Google ads: at most every 8 weeks, in case they start
Google is spaced out because it's ~95% of the Apify bill and loses little: each check asks for every ad shown
since the last one, so a later check catches up. Since Nov 2026 a Google check lists the resort's ads for free
(gfree.py) and pays Apify only for creatives the library doesn't have yet; known ads get their last-shown date
from the free listing. If the free listing fails, the check falls back to the paid domain search. Meta only shows ads that are live at that moment, so a
missed Meta check loses ads for good - it stays frequent (and it's cheap).
Each run takes the weekly-Meta groups first, then the most overdue, then resorts never checked (best
prospects first), up to MAX_JOBS Apify jobs; the next hourly run carries on.

Budget: jobs only start while this period's Apify spend plus the job's likely cost stays under
APIFY_MONTHLY_BUDGET minus META_RESERVE; prospects' Meta checks may use the reserve too. So when credit runs
low, everything else pauses first and prospects' Meta keeps going until the period resets. Apify's own limit (default $19 plan) always caps it.
A resort's first check only pulls Google ads shown in the last FIRST_DAYS days (max FIRST_GOOGLE).
A job that fails is skipped for the rest of the day (data/collect_fails.json) so it can't eat the budget.
"""
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

import collect
import gfree
import library
import roster

BUDGET = float(os.environ.get("APIFY_MONTHLY_BUDGET") or 18.8)  # just under the $19 plan's limit
MAX_JOBS = int(os.environ.get("MAX_JOBS_PER_RUN") or 60)
GROUPS = {"prospect": (7, 14), "benchmark": (14, 28), "mid": (14, 42), "low": (28, 84)}  # (Meta, Google) days
NO_GOOGLE_EVERY = 56
META_RESERVE = float(os.environ.get("APIFY_META_RESERVE") or 1.5)  # last $ of the budget, kept for prospects' Meta
FIRST_DAYS, FIRST_GOOGLE, GOOGLE_CAP, META_CAP = 120, 30, 50, 150
PASS_META_CAP = 500  # Ikon / Epic run ~300 live Meta ads
# A job's likely worst cost, for the budget check. Apify bills about 40% more than runs.csv logs
# (Nov 2026: Google ~$0.0022 per ad billed), so these are set from the bill, not the log.
EST = {"meta": 0.03, "meta_pass": 0.5, "google": 0.12, "google_first": 0.07}
GOOGLE_BIG = 100  # Google cap for a resort whose last check came back full (see google_cap)
ALERTS = os.path.join(library.DATA, "alerts.json")  # when the 'Meta is broken' email last went out
FAILS = os.path.join(library.DATA, "collect_fails.json")
EMPTY = os.path.join(library.DATA, "meta_empty.json")  # {meta:slug: [days its Meta check came back empty]}


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
        rank = roster.num(r.get("priority_rank")) or roster.num(r.get("atlas_rank")) or 999
        every = GROUPS.get(r.get("group"), GROUPS["low"])
        for p in platforms:
            if not (r.get("meta_page_id") if p == "meta" else r.get("domain")):
                continue
            d = last.get((p, r["slug"]))
            age = (today - date.fromisoformat(d)).days if d else 999
            days = (int(r["meta_every"]) if r.get("meta_every") else every[0]) if p == "meta" else every[1]
            if p == "google" and r.get("google_known") == "no":
                days = max(days, NO_GOOGLE_EVERY)
            if days == 7:  # weekly: Monday's round, or any day once a check is overdue
                ok = (force and age >= 1) or (monday and age >= 5) or age >= 8
            else:
                ok = age >= days - 1
            if ok:
                order = 1 + list(GROUPS).index(r.get("group") if r.get("group") in GROUPS else "low")
                if weekly and p == "meta":  # weekly Meta first
                    order = 0
                jobs.append(((order, 0 if d else 1, -age if d else rank), p, r, d))
    jobs.sort(key=lambda j: j[0])
    return jobs


def mark(st, now, platforms, fails, paused=()):
    """The Monday report waits (st meta_last / google_last) until every weekly resort is checked.
    paused: platforms out of budget this period - the report goes out without waiting for them."""
    if now.weekday() == 0 and now.hour < 12:
        return
    left = [j for j in due(now, platforms) if j[2].get("tier") == "weekly" and f"{j[1]}:{j[2]['slug']}" not in fails]
    for p in platforms:
        if p in paused or not any(j[1] == p for j in left):
            st[f"{p}_last"] = now.date().isoformat()


def google_cap(slug, d):
    """Ads to ask Google for: FIRST_GOOGLE on a first check, GOOGLE_CAP after that, GOOGLE_BIG when the last check
    came back full (otherwise a busy resort loses ads, and its running ads look stopped)."""
    if not d:
        return FIRST_GOOGLE
    try:
        n = len(library.read_raw(os.path.join(library.DATA, "raw", "google", d, slug + ".json.gz")))
    except Exception:
        n = 0
    return GOOGLE_BIG if n >= GOOGLE_CAP else GOOGLE_CAP


_KNOWN, _LOCK = {}, __import__("threading").Lock()


def known_google(slug):
    """Creative ids this resort's earlier Google checks already bought full details for (not free listing rows)."""
    with _LOCK:
        if not _KNOWN:
            _load_known()
        return _KNOWN.setdefault(slug, set())


def _load_known():
    if not _KNOWN:
        for d, sl, path in library.raw_files("google"):
            ids = _KNOWN.setdefault(sl, set())
            for a in library.read_raw(path):
                if a.get("creativeId") and not a.get("_listing"):
                    ids.add(str(a["creativeId"]))
        _KNOWN["_loaded"] = set()


def google_free(r, d, since, token, label, now):
    """A Google check that only pays for new ads: free listing, then Apify for creatives we don't have yet.
    Returns (items, run info) like collect.run_actor; items mix paid detail rows and free listing rows."""
    country = r.get("country") or "US"
    listed = gfree.list_creatives(r["domain"], country)
    recent = [x for x in listed if (x.get("lastShown") or "")[:10] >= since.isoformat()]
    known = known_google(r["slug"])
    new = sorted((x for x in recent if x["creativeId"] not in known), key=lambda x: x.get("firstShown") or "", reverse=True)
    cap = FIRST_GOOGLE if not d else GOOGLE_BIG
    buy = new[:cap]
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    info = {"label": label, "actor": "gfree (free listing)", "run_id": "", "status": "SUCCEEDED", "items": 0,
            "cost_usd": 0, "started": stamp, "finished": stamp}
    items = []
    if buy:
        try:
            got, info = collect.run_actor(collect.GOOGLE_ACTOR, gfree.details_input(buy, country), token, label)
        except Exception as e:
            raise gfree.ListingFailed(f"details for new ads failed: {str(e)[:120]}")
        if info["status"] != "SUCCEEDED":
            collect.append_runs([info])  # log what that attempt cost before the paid domain search runs
            raise gfree.ListingFailed(f"details for new ads came back {info['status']}")
        items = [x for x in got if isinstance(x, dict) and x.get("creativeId")]
        if not items:
            print(f"::warning::{label}: Apify returned no details for {len(buy)} new ads - they will be retried next check")
    have = {str(x.get("creativeId")) for x in items}
    # listing rows only for ads already in the library (to move their last-shown date); new ads that weren't
    # bought this time (over the cap, or Apify failed) wait for the next check instead of showing up blank
    items += [x for x in recent if x["creativeId"] in known and x["creativeId"] not in have]
    with _LOCK:
        known |= have
    info["items"] = len(items)
    print(f"  {label}: {len(listed)} ads listed free, {len(recent)} shown since {since}, {len(new)} new, "
          f"paid details for {len(have)}" + (f" ({len(new) - len(buy)} more next check)" if len(new) > len(buy) else "")
          + f", ${info['cost_usd']}")
    return items, info


def meta_alert(infos, today):
    """Emails you once a day while Meta collection looks broken, and once when it works again."""
    try:
        metas = [i for i in infos if i["label"].startswith("meta:")]
        if not metas:
            return
        good = [i for i in metas if i["status"] == "SUCCEEDED" and i["items"]]
        errors = [i for i in metas if i["status"] != "SUCCEEDED"]
        passes = [i for i in metas if i["label"] in ("meta:ikon-pass", "meta:epic-pass") and i["status"] == "SUCCEEDED" and not i["items"]]
        broken = (len(metas) >= 5 and not good) or len(errors) >= max(3, len(metas) // 2) or bool(passes)
        st = library.load_json(ALERTS, {})
        mail = __import__("mailer").send_email
        if broken and st.get("meta_sent") != today:
            why = (f"{len(errors)} of {len(metas)} Meta checks failed outright" if errors else
                   f"{len(metas) - len(good)} of {len(metas)} Meta checks came back with no ads, which usually means Facebook is blocking the scraper")
            if passes and not errors:
                why += " (even Ikon / Epic, which always have ads running)"
            lines = [f"Meta collection looks broken ({today}): {why}.", "",
                     f"Scraper in use: {collect.META_ACTOR} (META_ACTOR in collect.py)", "", "Checks this run:"]
            lines += [f"  {i['label']}: {i['status']}, {i['items']} ads" + (f", https://console.apify.com/view/runs/{i['run_id']}" if i.get("run_id") else "") for i in metas[:12]]
            lines += ["", "What to check:",
                      "  1. Open one of the Apify runs above and read the end of its log (blocked? login wall? out of credit?).",
                      "  2. Apify > Billing: is this month's usage limit or credit used up?",
                      "  3. Try the scraper by hand on one resort in the Apify console. If Facebook blocks it, switch to another Ad Library scraper and change META_ACTOR in collect.py.",
                      "", "Meanwhile Google collection, the site and the Monday report keep going. Meta ads still running when it's fixed are picked up then; ads that start and stop while it's down are missed.",
                      "You get one of these a day while it stays broken, and one email when it works again."]
            if mail("Ad tracker: Meta collection isn't working", "\n".join(lines)):
                st["meta_sent"] = today
            st["meta_down_since"] = st.get("meta_down_since") or today
        elif good and not broken and st.get("meta_down_since"):
            mail("Ad tracker: Meta collection is working again",
                 f"Meta is back as of {today}: {len(good)} of {len(metas)} checks returned ads. It was down since {st['meta_down_since']}.")
            st.pop("meta_down_since", None)
            st.pop("meta_sent", None)
        library.save_json(ALERTS, st, indent=1)
    except Exception as e:
        print(" Meta alert check failed:", str(e)[:150])


def run(st, now, platforms=("meta", "google"), force=False):
    """Collect whatever is due, within budget. force: re-check the weekly resorts now (manual runs)."""
    today = now.date().isoformat()
    fails = {k: v for k, v in library.load_json(FAILS, {}).items() if v == today}
    zeros = library.load_json(EMPTY, {})
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
    spent = used if used is not None else month_spend(now.date())  # Apify's own figure for this billing period
    left, picked, starved = budget - spent, [], set()
    for _, p, r, d in jobs:
        if p == "meta":
            est = EST["meta_pass" if r.get("state") == "PASS" else "meta"] * max(1, str(r.get("meta_page_id") or "").count(";") + 1)
        else:
            est = EST["google_first" if not d else "google"] * (2 if d and google_cap(r["slug"], d) > GOOGLE_CAP else 1)
        reserved = p == "meta" and r.get("group") == "prospect"  # the reserve is for prospects' Meta only
        room = left - (0 if reserved else META_RESERVE)
        if len(picked) < MAX_JOBS and est <= room:
            left -= est
            picked.append((p, r, d))
        elif est > room:
            starved.add(p)
    wait = len(jobs) - len(picked)
    print(f"Collection: {len(jobs)} jobs due ({sum(j[2].get('tier') == 'weekly' for j in jobs)} weekly), running {len(picked)}; "
          f"Apify ${spent:.2f} used of ${budget:.2f} this period" + (f"; {wait} wait for the next run / period" if wait else "")
          + ("; low on credit: only prospects' Meta runs until the Apify period resets" if starved else ""))
    # a platform the budget has run out for doesn't hold up the Monday report
    paused = tuple(p for p in starved if not any(x[0] == p for x in picked))
    if not picked:
        return mark(st, now, platforms, fails, paused)

    def work(job):
        p, r, d = job
        label = f"{p}:{r['slug']}"
        if p == "meta":
            actor, payload = collect.META_ACTOR, collect.meta_input(r, PASS_META_CAP if r.get("state") == "PASS" else META_CAP)
        else:
            since = (date.fromisoformat(d) - timedelta(days=3)) if d else (now.date() - timedelta(days=FIRST_DAYS))
            actor, payload = collect.GOOGLE_ACTOR, collect.google_input(r, google_cap(r["slug"], d), since.isoformat())
        try:
            if p == "google":
                try:  # free listing first; Apify only for ads the library hasn't got (gfree.py)
                    items, info = google_free(r, d, since, token, label, now)
                except gfree.ListingFailed as e:
                    print(f"  {label}: free listing failed ({e}) - paid domain search instead")
                    items, info = collect.run_actor(actor, payload, token, label)
            else:
                items, info = collect.run_actor(actor, payload, token, label)
        except Exception as e:
            print(f"  {label} failed: {str(e)[:200]}")
            fails[label] = today
            return {"label": label, "actor": actor, "status": "ERROR", "items": 0, "cost_usd": 0,
                    "run_id": "", "started": "", "finished": ""}
        if info["status"] == "SUCCEEDED" and p == "meta" and not items:
            seen = zeros.setdefault(label, [])
            if today not in seen:
                seen.append(today)
            if len(seen) < 3:  # usually Facebook blocking the scraper, not a resort without ads: retry tomorrow
                print(f"  {label}: no Meta ads returned - treated as blocked, retry tomorrow")
                fails[label] = today
                return info
            items = [{"checked_empty": True}]  # empty on 3 different days: really no Meta ads now
        elif p == "meta" and items:
            zeros.pop(label, None)
        if info["status"] == "SUCCEEDED":
            collect.save_raw(p, r["slug"], items, today)
        else:  # half-finished: don't save it (it would end ads that are still running); retry tomorrow
            fails[label] = today
        return info

    with ThreadPoolExecutor(max_workers=3) as ex:
        infos = list(ex.map(work, picked))
    collect.append_runs(infos)
    library.save_json(FAILS, fails, indent=1)
    library.save_json(EMPTY, zeros, indent=1)
    meta_alert(infos, today)  # emails you when Meta collection breaks, and when it's back
    metas = [i for i in infos if i["label"].startswith("meta:") and i["status"] == "SUCCEEDED"]
    if len(metas) >= 3 and not any(i["items"] for i in metas):
        print("::warning::Meta returned no ads for any resort this run - Facebook is probably blocking the scraper")
    cost = sum(float(i["cost_usd"] or 0) for i in infos)
    print(f"Collected {sum(i['items'] for i in infos)} ads in {len(infos)} jobs, Apify ${cost:.2f}, "
          f"{sum(i['status'] != 'SUCCEEDED' for i in infos)} failed")
    mark(st, now, platforms, fails, paused)
