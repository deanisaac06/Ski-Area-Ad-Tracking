"""Ad library collector (pilot): pull every resort's Meta and Google ads through Apify.

For each resort in resorts.csv (pilot=yes) it runs:
  - Meta:   curious_coder/facebook-ads-library-scraper on the resort's Ad Library page (US, active ads)
  - Google: silva95gustavo/google-ads-scraper on the resort's domain (US region, full history)
One Apify run per resort per platform keeps every ad tied to the right resort.

Saves:
  data/raw/<platform>/<date>/<slug>.json.gz   - untouched Apify output (library.py builds everything from these)
  data/runs.csv                               - every Apify run with its cost, so spend is always visible

Run:  APIFY_TOKEN=... python collect.py [--platform meta|google|both] [--only slug] [--limit N]
"""
import argparse
import csv
import gzip
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
API = "https://api.apify.com/v2"
META_ACTOR = "automation-lab~facebook-ads-library"  # curious_coder~facebook-ads-library-scraper got blocked by Facebook (Nov 2026)
GOOGLE_ACTOR = "silva95gustavo~google-ads-scraper"


# ------------------------------------------------------------------ Apify
def run_actor(actor, payload, token, label, timeout_min=30):
    """Start an actor run, wait for it, return (items, run_info)."""
    r = requests.post(f"{API}/acts/{actor}/runs", params={"token": token}, json=payload, timeout=60)
    r.raise_for_status()
    run = r.json()["data"]
    deadline = time.time() + timeout_min * 60
    while run["status"] in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(10)
        run = requests.get(f"{API}/actor-runs/{run['id']}", params={"token": token}, timeout=60).json()["data"]
    items = []
    if run.get("defaultDatasetId"):
        offset = 0
        while True:
            page = requests.get(f"{API}/datasets/{run['defaultDatasetId']}/items",
                                params={"token": token, "clean": "true", "offset": offset, "limit": 1000},
                                timeout=120).json()
            items += page
            if len(page) < 1000:
                break
            offset += 1000
    items = [meta_to_old(x) for x in items] if actor == META_ACTOR else items
    info = {"label": label, "actor": actor, "run_id": run["id"], "status": run["status"],
            "items": len(items), "cost_usd": round(run.get("usageTotalUsd") or 0, 4),
            "started": run.get("startedAt"), "finished": run.get("finishedAt")}
    print(f"  {label}: {run['status']}, {len(items)} items, ${info['cost_usd']}")
    return items, info


def meta_to_old(x):
    """automation-lab output -> the curious_coder shape library.py reads (old downloads keep working)."""
    if not isinstance(x, dict) or "snapshot" in x or x.get("error"):
        return x
    fmt = str(x.get("displayFormat") or "").upper()
    imgs = [u for u in (x.get("imageUrls") or []) if u]
    vids = [v for v in (x.get("videoUrls") or []) if v]
    prev = x.get("videoPreviewUrls") or []
    snap = {"body": {"text": x.get("bodyText") or ""}, "title": x.get("title") or "",
            "link_url": x.get("linkUrl") or "", "link_description": x.get("linkDescription") or "",
            "caption": x.get("linkCaption") or "", "cta_text": x.get("ctaText") or "", "cta_type": x.get("ctaType") or "",
            "display_format": fmt, "page_name": x.get("pageName") or "",
            "images": [{"original_image_url": u} for u in imgs],
            "videos": [{"video_hd_url": v, "video_preview_image_url": prev[i] if i < len(prev) else ""} for i, v in enumerate(vids)],
            "cards": []}
    if fmt in ("CAROUSEL", "MULTI_IMAGES") and len(imgs) > 1:
        snap["cards"] = [{"original_image_url": u, "title": snap["title"], "link_url": snap["link_url"]} for u in imgs]
    return {"ad_archive_id": str(x.get("adArchiveId") or ""), "page_id": str(x.get("pageId") or ""),
            "page_name": x.get("pageName") or "", "is_active": x.get("isActive"),
            "start_date": x.get("startDate") or "", "end_date": x.get("endDate") or "",
            "publisher_platform": [str(p).upper() for p in (x.get("platforms") or [])],
            "collation_count": x.get("collationCount") or 1, "collation_id": str(x.get("collationId") or ""),
            "ad_library_url": x.get("adLibraryUrl") or "", "contains_ai_media": x.get("containsAiMedia"),
            "snapshot": snap, "source": "automation-lab"}

def meta_input(resort, limit):
    url = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=" + (resort.get("country") or "US")
           + f"&media_type=all&search_type=page&view_all_page_id={resort['meta_page_id']}")
    return {"adsLibraryUrls": [url], "maxAds": limit, "activeStatus": "active", "country": resort.get("country") or "US",
            "mediaType": "all", "includeAdDetails": False}


def google_input(resort, limit, since=None):
    p = {"domains": [resort["domain"]], "region": resort.get("country") or "US", "resultsLimit": limit,
         "shouldDownloadAssets": False, "shouldDownloadPreviews": False, "skipDetails": False}
    if since:                     # only ads shown since then (new ads + updated last-shown dates for running ones)
        p["startDate"] = since
    return p


def fetch_items(dataset_id, token):
    items, offset = [], 0
    while True:
        page = requests.get(f"{API}/datasets/{dataset_id}/items",
                            params={"token": token, "clean": "true", "offset": offset, "limit": 1000}, timeout=120).json()
        items += page
        if len(page) < 1000:
            return items
        offset += 1000


def reuse_runs(since, resorts, token):
    """Results of Apify runs that already finished since `since` (ISO time), keyed by (platform, slug).
    Used when a collection ran fine but its results never got saved - no need to pay for it twice."""
    by_page = {r["meta_page_id"]: r for r in resorts if r.get("meta_page_id")}
    by_domain = {r["domain"]: r for r in resorts if r.get("domain")}
    runs = requests.get(f"{API}/actor-runs", params={"token": token, "desc": 1, "limit": 200}, timeout=60).json()["data"]["items"]
    found = {}
    for run in runs:
        if run.get("startedAt", "") < since or run.get("status") != "SUCCEEDED":
            continue
        inp = requests.get(f"{API}/key-value-stores/{run['defaultKeyValueStoreId']}/records/INPUT",
                           params={"token": token}, timeout=60).json()
        resort, platform = None, None
        if inp.get("domains"):
            platform, resort = "google", by_domain.get(inp["domains"][0])
        elif inp.get("urls") or inp.get("adsLibraryUrls"):
            page_id = str((inp.get("adsLibraryUrls") or [None])[0] or (inp.get("urls") or [{}])[0].get("url", "")).split("view_all_page_id=")[-1]
            platform, resort = "meta", by_page.get(page_id)
        if not resort or (platform, resort["slug"]) in found:
            continue                                 # newest run per resort/platform wins
        full = requests.get(f"{API}/actor-runs/{run['id']}", params={"token": token}, timeout=60).json()["data"]
        items = fetch_items(run["defaultDatasetId"], token)
        items = [meta_to_old(x) for x in items] if platform == "meta" else items
        info = {"label": f"{platform}:{resort['slug']}", "actor": META_ACTOR if platform == "meta" else GOOGLE_ACTOR,
                "run_id": run["id"], "status": "REUSED", "items": len(items),
                "cost_usd": round(full.get("usageTotalUsd") or 0, 4),
                "started": run.get("startedAt"), "finished": run.get("finishedAt")}
        print(f"  {info['label']}: reused run {run['id']}, {len(items)} items")
        found[(platform, resort["slug"])] = (items, info)
    return found


# ------------------------------------------------------------------ storage
def save_raw(platform, slug, items, day):
    d = os.path.join(DATA, "raw", platform, day)
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f"{slug}.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(items, f)


def append_runs(infos):
    path = os.path.join(DATA, "runs.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["label", "actor", "run_id", "status", "items", "cost_usd", "started", "finished"])
        if new:
            w.writeheader()
        w.writerows(infos)


# ------------------------------------------------------------------ main
def load_resorts(only=None):
    resorts = __import__("roster").load()  # resorts.csv + every ski area in the atlas
    return [r for r in resorts if not only or r["slug"] == only]


def _old_load_resorts(only=None):
    with open(os.path.join(HERE, "resorts.csv"), newline="", encoding="utf-8") as f:
        resorts = [r for r in csv.DictReader(f) if r.get("pilot", "").lower() == "yes"]
    return [r for r in resorts if not only or r["slug"] == only]


def collect(platforms=("meta", "google"), limit=150, google_limit=50, google_since=None, reuse_since="",
            only=None, parallel=3):
    """Run the Apify scrapers and save each resort's raw download. Returns the run log rows."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("APIFY_TOKEN is not set - add it as a repository secret")
    resorts = load_resorts(only)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(DATA, exist_ok=True)
    jobs = [(p, r) for r in resorts for p in platforms if (r.get("meta_page_id") if p == "meta" else r.get("domain"))]
    reused = reuse_runs(reuse_since, resorts, token) if reuse_since else {}

    def work(job):
        platform, r = job
        if (platform, r["slug"]) in reused:
            items, info = reused[(platform, r["slug"])]
            save_raw(platform, r["slug"], items, today)
            return info
        actor, payload = ((META_ACTOR, meta_input(r, limit)) if platform == "meta"
                          else (GOOGLE_ACTOR, google_input(r, min(limit, google_limit), google_since)))
        try:
            items, info = run_actor(actor, payload, token, f"{platform}:{r['slug']}")
            if platform == "google" and google_since and info["status"] != "SUCCEEDED":
                print(f"  {platform}:{r['slug']}: retrying without the date filter")
                items, info = run_actor(actor, google_input(r, min(limit, google_limit)), token, f"{platform}:{r['slug']}")
        except Exception as e:
            print(f"  {platform}:{r['slug']} failed: {str(e)[:200]}")
            return {"label": f"{platform}:{r['slug']}", "actor": actor, "status": "ERROR",
                    "items": 0, "cost_usd": 0, "run_id": "", "started": "", "finished": ""}
        save_raw(platform, r["slug"], items, today)
        return info

    print(f"Collecting {', '.join(platforms)}: {len(jobs)} Apify jobs for {len(resorts)} resorts "
          f"(Meta up to {limit}, Google up to {min(limit, google_limit)}{' since ' + google_since if google_since else ''})")
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        infos = list(ex.map(work, jobs))
    append_runs(infos)
    cost = sum(float(i["cost_usd"] or 0) for i in infos)
    print(f"Collected {sum(i['items'] for i in infos)} ads, Apify cost ${cost:.2f}, "
          f"{sum(i['status'] not in ('SUCCEEDED', 'REUSED') for i in infos)} jobs failed")
    return infos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="both", choices=["meta", "google", "both"])
    ap.add_argument("--only", help="one resort slug")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("ADS_PER_RESORT", 150)))
    # Google is billed per ad with details (~$0.002 each), so it gets its own, lower cap
    ap.add_argument("--google-limit", type=int, default=int(os.environ.get("GOOGLE_ADS_PER_RESORT", 50)))
    ap.add_argument("--google-since", default="", help="YYYY-MM-DD: only Google ads shown since then")
    ap.add_argument("--reuse-since", default=os.environ.get("REUSE_SINCE", ""),
                    help="ISO time: use Apify runs that already finished since then instead of starting new ones")
    ap.add_argument("--parallel", type=int, default=3)
    args = ap.parse_args()
    platforms = ("meta", "google") if args.platform == "both" else (args.platform,)
    collect(platforms, args.limit, args.google_limit, args.google_since or None, args.reuse_since, args.only, args.parallel)


if __name__ == "__main__":
    main()
