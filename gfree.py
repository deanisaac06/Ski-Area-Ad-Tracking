"""Free Google ad listing, so Apify is only paid for ads we haven't seen before.

Google's Ads Transparency Center (adstransparency.google.com) lists every ad pointing at a domain, with its
advertiser, creative id and first / last shown dates, through the same public request its own web page makes.
That listing costs nothing. The Apify Google scraper charges about $0.0016-0.0022 for every ad it returns,
whether or not we already have it, and most of each check used to be ads already in the library (e.g. 1,054 of
1,085 on Nov 23, 2026) re-bought just to learn they were still running.

So a Google check (cadence.py) now:
  1. lists the resort's ads here for free (all pages, capped at MAX_PAGES),
  2. keeps the ones shown since the last check (the same window the paid check used),
  3. pays Apify only for creatives the library doesn't have full details for yet (the newest first, capped),
  4. saves the rest as free "listing" rows: library.py uses them to move each known ad's last-shown date
     forward, keeping its details from the earlier paid download.
If the free listing fails (Google changes the page, or blocks the runner), the check falls back to the old paid
domain search, so there are no gaps.

Run:  python gfree.py skitaos.com [US|CA]     (prints what the free listing sees)
"""
import json
import sys
import time
from datetime import datetime, timezone

import requests

URL = "https://adstransparency.google.com/anji/_/rpc/SearchService/SearchCreatives?authuser=0"
HOME = "https://adstransparency.google.com/?region=US"
REGION = {"US": 2840, "CA": 2124}
PAGE, MAX_PAGES = 40, 30          # up to 1,200 ads per domain
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124 Safari/537.36",
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Origin": "https://adstransparency.google.com",
      "Referer": "https://adstransparency.google.com/"}
_session = None
_lock = __import__("threading").Lock()


class ListingFailed(Exception):
    pass


def session():
    global _session
    with _lock:
        if _session is not None:
            return _session
        sess = requests.Session()
        sess.headers.update(UA)
        try:
            sess.get(HOME, timeout=30)  # picks up the cookies a browser would have
        except requests.RequestException:
            pass
        _session = sess
        return _session


def _iso(sec):
    try:
        return datetime.fromtimestamp(int(sec), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (TypeError, ValueError):
        return ""


def to_item(x, country):
    """One listing entry in the shape the Apify scraper's items have (fields library.py reads), marked _listing."""
    ar, cr = x.get("1") or "", x.get("2") or ""
    return {"advertiserId": ar, "creativeId": cr, "advertiserName": x.get("12") or "",
            "firstShown": _iso((x.get("6") or {}).get("1")), "lastShown": _iso((x.get("7") or {}).get("1")),
            "numServedDays": x.get("13") or 0, "domain": x.get("14") or "",
            "adLibraryUrl": f"https://adstransparency.google.com/advertiser/{ar}/creative/{cr}" if ar and cr else "",
            "regionCode": country, "_listing": True, "source": "atc-free"}


def list_creatives(domain, country="US", max_pages=MAX_PAGES):
    """Every ad Google lists for a domain in a region (newest activity first, as Google orders them)."""
    region = REGION.get(country, 2840)
    s, out, token = session(), [], None
    for page in range(max_pages):
        req = {"2": PAGE, "3": {"8": [region], "12": {"1": domain, "2": True}}, "7": {"1": 1, "2": 24, "3": region}}
        if token:
            req["4"] = token
        for attempt in range(3):
            try:
                r = s.post(URL, data={"f.req": json.dumps(req, separators=(",", ":"))}, timeout=30)
                if r.status_code == 429:
                    time.sleep(10 * (attempt + 1))
                    continue
                r.raise_for_status()
                j = r.json()
                break
            except (requests.RequestException, ValueError) as e:
                if attempt == 2:
                    raise ListingFailed(f"{domain}: {str(e)[:150]}")
                time.sleep(3)
        else:
            raise ListingFailed(f"{domain}: rate limited")
        if not isinstance(j, dict):
            raise ListingFailed(f"{domain}: unexpected answer")
        rows = j.get("1") or []
        out += [to_item(x, country) for x in rows if isinstance(x, dict) and x.get("2")]
        token = j.get("2")
        if not token or not rows:
            break
        time.sleep(0.4)
    return out


def ad_url(item, country="US"):
    return f"https://adstransparency.google.com/advertiser/{item['advertiserId']}/creative/{item['creativeId']}?region={country}"


def details_input(items, country="US"):
    """Apify input that fetches full details for just these creatives (individual-ad URLs)."""
    return {"startUrls": [{"url": ad_url(x, country)} for x in items], "region": country,
            "resultsLimit": len(items), "shouldDownloadAssets": False, "shouldDownloadPreviews": False,
            "skipDetails": False}


if __name__ == "__main__":
    dom = sys.argv[1] if len(sys.argv) > 1 else "skitaos.com"
    got = list_creatives(dom, sys.argv[2] if len(sys.argv) > 2 else "US")
    print(f"{dom}: {len(got)} ads listed for free")
    for x in got[:10]:
        print(f"  {x['creativeId']}  {x['firstShown'][:10]} -> {x['lastShown'][:10]}  {x['advertiserName']}")
