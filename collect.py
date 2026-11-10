"""Ad library collector (pilot): pull every resort's Meta and Google ads through Apify.

For each resort in resorts.csv (pilot=yes) it runs:
  - Meta:   curious_coder/facebook-ads-library-scraper on the resort's Ad Library page (US, active ads)
  - Google: silva95gustavo/google-ads-scraper on the resort's domain (US region, full history)
One Apify run per resort per platform keeps every ad tied to the right resort.

Saves:
  data/raw/<platform>/<date>/<slug>.json.gz   - untouched Apify output (for checking field names in the pilot)
  data/ads_meta.csv, data/ads_google.csv      - one row per ad, merged across runs (first_seen / last_seen)
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
META_ACTOR = "curious_coder~facebook-ads-library-scraper"
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
    info = {"label": label, "actor": actor, "run_id": run["id"], "status": run["status"],
            "items": len(items), "cost_usd": round(run.get("usageTotalUsd") or 0, 4),
            "started": run.get("startedAt"), "finished": run.get("finishedAt")}
    print(f"  {label}: {run['status']}, {len(items)} items, ${info['cost_usd']}")
    return items, info


def meta_input(resort, limit):
    url = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US"
           f"&media_type=all&search_type=page&view_all_page_id={resort['meta_page_id']}")
    return {"urls": [{"url": url}], "count": limit, "limitPerSource": limit, "scrapeAdDetails": True,
            "scrapePageAds.activeStatus": "active", "scrapePageAds.countryCode": "US"}


def google_input(resort, limit):
    return {"domains": [resort["domain"]], "region": "US", "resultsLimit": limit,
            "shouldDownloadAssets": False, "shouldDownloadPreviews": False, "skipDetails": False}


# ------------------------------------------------------------------ normalizing
def dig(d, *paths, default=""):
    """First non-empty value among dotted paths, e.g. dig(ad, 'snapshot.body.text', 'body')."""
    for p in paths:
        v = d
        for k in p.split("."):
            v = v.get(k) if isinstance(v, dict) else None
            if v is None:
                break
        if v not in (None, "", [], {}):
            return v
    return default


def ts(v):
    if isinstance(v, (int, float)) and v > 0:
        return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d")
    return str(v or "")[:10]


def norm_meta(ad, resort):
    snap = ad.get("snapshot") or {}
    cards = snap.get("cards") or []
    videos = snap.get("videos") or [c for c in cards if c.get("video_hd_url") or c.get("video_sd_url")]
    images = snap.get("images") or [c for c in cards if c.get("original_image_url") or c.get("resized_image_url")]
    first_video = videos[0] if videos else {}
    first_image = images[0] if images else {}
    return {
        "ad_id": str(dig(ad, "ad_archive_id", "adArchiveID", "id")),
        "resort": resort["resort"], "slug": resort["slug"],
        "page_name": dig(ad, "page_name", "snapshot.page_name"),
        "start": ts(dig(ad, "start_date", "startDate")), "end": ts(dig(ad, "end_date", "endDate")),
        "active": dig(ad, "is_active", "isActive", default=""),
        "format": dig(snap, "display_format", default=""),
        "platforms": "|".join(dig(ad, "publisher_platform", "publisherPlatform", default=[]) or []),
        "versions": dig(ad, "collation_count", "collationCount", default=""),
        "collation_id": dig(ad, "collation_id", "collationID", default=""),
        "body": str(dig(snap, "body.text", "body", default=""))[:2000],
        "title": dig(snap, "title", default=""),
        "link_description": dig(snap, "link_description", default=""),
        "cta": dig(snap, "cta_text", default=""),
        "link": dig(snap, "link_url", default=""),
        "video_url": dig(first_video, "video_hd_url", "video_sd_url", default=""),
        "image_url": dig(first_image, "original_image_url", "resized_image_url", default="")
                     or dig(first_video, "video_preview_image_url", default=""),
        "n_cards": len(cards),
    }


def norm_google(ad, resort):
    return {
        "ad_id": str(dig(ad, "creativeId", "creative_id", "id", "adId")),
        "resort": resort["resort"], "slug": resort["slug"], "domain": resort["domain"],
        "advertiser": dig(ad, "advertiserName", "advertiser.name", "advertiser_name"),
        "advertiser_id": dig(ad, "advertiserId", "advertiser.id", "advertiser_id"),
        "format": dig(ad, "format", "adFormat", "creativeFormat"),
        "first_shown": ts(dig(ad, "firstShown", "first_shown", "firstShownDate", "startDate")),
        "last_shown": ts(dig(ad, "lastShown", "last_shown", "lastShownDate", "endDate")),
        "regions": "|".join(map(str, dig(ad, "regions", "regionStats", default=[]) or []))[:300]
        if isinstance(dig(ad, "regions", default=[]), list) else str(dig(ad, "regions"))[:300],
        "preview_url": dig(ad, "previewUrl", "imageUrl", "preview.imageUrl", "variations.0.imageUrl"),
        "url": dig(ad, "url", "adUrl", "transparencyUrl"),
    }


# ------------------------------------------------------------------ storage
def save_raw(platform, slug, items, day):
    d = os.path.join(DATA, "raw", platform, day)
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f"{slug}.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(items, f)


def merge(path, rows, key="ad_id", today=None):
    """Upsert rows by ad_id, keeping first_seen and updating last_seen."""
    existing = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            existing = {r[key]: r for r in csv.DictReader(f)}
    for r in rows:
        if not r.get(key):
            continue
        old = existing.get(r[key], {})
        r["first_seen"] = old.get("first_seen") or today
        r["last_seen"] = today
        existing[r[key]] = {**old, **r}
    cols = list(dict.fromkeys([c for r in existing.values() for c in r]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(sorted(existing.values(), key=lambda r: (r.get("slug", ""), r.get(key, ""))))
    return len(existing)


def append_runs(infos):
    path = os.path.join(DATA, "runs.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["label", "actor", "run_id", "status", "items", "cost_usd", "started", "finished"])
        if new:
            w.writeheader()
        w.writerows(infos)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="both", choices=["meta", "google", "both"])
    ap.add_argument("--only", help="one resort slug")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("ADS_PER_RESORT", 150)))
    ap.add_argument("--parallel", type=int, default=3)
    args = ap.parse_args()
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("APIFY_TOKEN is not set - add it as a repository secret")
    with open(os.path.join(HERE, "resorts.csv"), newline="", encoding="utf-8") as f:
        resorts = [r for r in csv.DictReader(f) if r.get("pilot", "").lower() == "yes"]
    if args.only:
        resorts = [r for r in resorts if r["slug"] == args.only]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(DATA, exist_ok=True)

    jobs = []
    for r in resorts:
        if args.platform in ("meta", "both") and r.get("meta_page_id"):
            jobs.append(("meta", r))
        if args.platform in ("google", "both") and r.get("domain"):
            jobs.append(("google", r))

    def work(job):
        platform, r = job
        actor, payload = ((META_ACTOR, meta_input(r, args.limit)) if platform == "meta"
                          else (GOOGLE_ACTOR, google_input(r, args.limit)))
        try:
            items, info = run_actor(actor, payload, token, f"{platform}:{r['slug']}")
        except Exception as e:
            print(f"  {platform}:{r['slug']} failed: {str(e)[:200]}")
            return platform, r, [], {"label": f"{platform}:{r['slug']}", "actor": actor, "status": "ERROR",
                                     "items": 0, "cost_usd": 0, "run_id": "", "started": "", "finished": ""}
        save_raw(platform, r["slug"], items, today)
        return platform, r, items, info

    print(f"Running {len(jobs)} Apify jobs for {len(resorts)} resorts (limit {args.limit} ads each)")
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        results = list(ex.map(work, jobs))

    meta_rows = [norm_meta(a, r) for p, r, items, _ in results if p == "meta" for a in items if isinstance(a, dict)]
    google_rows = [norm_google(a, r) for p, r, items, _ in results if p == "google" for a in items if isinstance(a, dict)]
    n_meta = merge(os.path.join(DATA, "ads_meta.csv"), meta_rows, today=today) if meta_rows else 0
    n_google = merge(os.path.join(DATA, "ads_google.csv"), google_rows, today=today) if google_rows else 0
    infos = [i for *_, i in results]
    append_runs(infos)
    cost = sum(float(i["cost_usd"] or 0) for i in infos)
    print(f"\nThis run: {len(meta_rows)} Meta ads, {len(google_rows)} Google ads, Apify cost ${cost:.2f}")
    print(f"Library totals: {n_meta} Meta ads, {n_google} Google ads")


if __name__ == "__main__":
    main()
