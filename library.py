"""Builds the ad library from every saved Apify download (data/raw/<platform>/<date>/<slug>.json.gz).

The raw downloads are the source of truth; everything else is rebuilt from them each run, so improving
how an ad is read applies to the whole history:
  data/ads_meta.csv, data/ads_google.csv  - one row per ad (spreadsheet-friendly)
  docs/data.js                            - everything the website needs (ads, scores, resort playbooks)

Run:  python library.py
"""
import csv
import glob
import gzip
import html
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DOCS = os.path.join(HERE, "docs")
TAGS = os.path.join(DATA, "tags.json")
MEDIA = os.path.join(DATA, "media.json")

CAMPAIGNS = ["Season passes", "Lift tickets & packs", "Lessons & learn-to", "Rentals & gear", "Lodging & getaways",
             "Events & weddings", "Dining & après", "Summer & activities", "Hiring", "Brand & general"]
THEMES = ["Price deadline", "Discount", "Kids & family", "Gift & holiday", "Snow & conditions", "Early season",
          "Uncrowded / local", "Luxury", "Beginner friendly", "Bundle / package", "Events", "Testimonial"]
REGIONS = {"West": "West", "East": "East", "Midwest": "Midwest", "Canada": "Canada"}


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def save_json(path, data, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def load_resorts():
    with open(os.path.join(HERE, "resorts.csv"), newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("pilot", "").strip().lower() == "yes"]


# ------------------------------------------------------------------ reading raw downloads
def raw_files(platform):
    """[(date, slug, path)] oldest first."""
    out = []
    for p in glob.glob(os.path.join(DATA, "raw", platform, "*", "*.json.gz")):
        out.append((os.path.basename(os.path.dirname(p)), os.path.basename(p)[:-8], p))
    return sorted(out)


def read_raw(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            items = json.load(f)
        return [a for a in items if isinstance(a, dict) and not a.get("error")]
    except Exception as e:
        print("  couldn't read", path, e)
        return []


def day(v):
    if isinstance(v, (int, float)) and v > 0:
        return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d")
    return str(v or "")[:10]


def clean(s, n=2000):
    s = html.unescape(str(s or ""))
    s = re.sub(r"<[A-Za-z][^<>]{0,40}>", "", s)                   # Google Maps ad placeholders like <Rating (Reviews)>
    s = re.sub(r"(\s*·\s*){2,}", " · ", s).strip(" ·\n")
    return "" if "{{" in s else s[:n]


def meta_ad(a, resort):
    s = a.get("snapshot") or {}
    cards = [c for c in (s.get("cards") or []) if isinstance(c, dict)]
    c0 = cards[0] if cards else {}
    pick = lambda k: clean(s.get(k)) or clean(c0.get(k))
    body = clean((s.get("body") or {}).get("text") if isinstance(s.get("body"), dict) else s.get("body")) or clean(c0.get("body"))
    videos = s.get("videos") or [c for c in cards if c.get("video_hd_url") or c.get("video_sd_url")]
    images = s.get("images") or [c for c in cards if c.get("original_image_url") or c.get("resized_image_url")] \
        or s.get("extra_images") or []
    v0, i0 = (videos[0] if videos else {}), (images[0] if images else {})
    img = i0.get("original_image_url") or i0.get("resized_image_url") or v0.get("video_preview_image_url") or ""
    vid = v0.get("video_hd_url") or v0.get("video_sd_url") or ""
    fmt = (s.get("display_format") or "").upper()
    kind = ("Video" if fmt == "VIDEO" or (videos and fmt in ("DCO", "")) else
            "Carousel" if fmt in ("CAROUSEL", "MULTI_IMAGES") else
            "Dynamic" if fmt == "DCO" else "Static")
    return {
        "id": str(a.get("ad_archive_id") or a.get("adArchiveID") or ""), "p": "meta",
        "slug": resort["slug"], "n": resort["resort"], "s": resort["state"], "rg": resort["region"],
        "start": day(a.get("start_date")), "fmt": fmt or "?", "kind": kind,
        "plats": [x.title().replace("_", " ") for x in (a.get("publisher_platform") or [])],
        "versions": a.get("collation_count") or 1, "group": str(a.get("collation_id") or ""),
        "title": pick("title"), "body": body, "desc": pick("link_description"),
        "cta": pick("cta_text"), "link": pick("link_url"), "n_cards": len(cards),
        "img_src": img, "video_src": vid, "cards_src": __import__("archive").meta_cards(s, cards),
        "url": a.get("ad_library_url") or f"https://www.facebook.com/ads/library/?id={a.get('ad_archive_id')}",
        "dynamic": fmt == "DCO",
    }


def google_ad(a, resort):
    vars_ = [v for v in (a.get("variations") or []) if isinstance(v, dict)]
    first = lambda k: next((clean(v[k]) for v in vars_ if v.get(k)), "")
    stats = a.get("regionStats") or []
    surfaces = sorted({x.get("surfaceName", "") for r in stats if isinstance(r, dict)
                       for x in r.get("surfaceServingStats") or [] if x.get("surfaceName")})
    fmt = (a.get("format") or "").upper()
    heads = list(dict.fromkeys(clean(v["headline"]) for v in vars_ if v.get("headline")))[:4]
    return {
        "id": str(a.get("creativeId") or ""), "p": "google",
        "slug": resort["slug"], "n": resort["resort"], "s": resort["state"], "rg": resort["region"],
        "start": day(a.get("firstShown")), "last_shown": day(a.get("lastShown")),
        "served_days": a.get("numServedDays") or 0,
        "fmt": fmt, "kind": {"VIDEO": "Video", "IMAGE": "Static", "TEXT": "Text"}.get(fmt, fmt.title()),
        "advertiser": a.get("advertiserName") or "", "advertiser_id": a.get("advertiserId") or "",
        "versions": max(1, len(vars_)),
        "title": heads[0] if heads else "", "headlines": heads,
        "body": first("body") or first("description"), "desc": first("description") if first("body") else "",
        "cta": first("cta"), "link": first("clickUrl"),
        "img_src": a.get("previewUrl") or first("imageUrl"), "video_src": first("videoUrl"), "yt": __import__("archive").yt_id(a) if fmt == "VIDEO" else "", "cards_src": __import__("archive").google_cards(vars_),
        "regions": a.get("creativeRegions") or [], "surfaces": surfaces,
        "url": a.get("adLibraryUrl") or "",
    }


def build_ads():
    """All ads across every download, with first/last seen and whether they're still live."""
    resorts = {r["slug"]: r for r in load_resorts()}
    ads, latest_run = {}, {}
    for platform, reader in (("meta", meta_ad), ("google", google_ad)):
        for d, slug, path in raw_files(platform):
            if slug not in resorts:
                continue
            latest_run[(platform, slug)] = max(latest_run.get((platform, slug), ""), d)
            for a in read_raw(path):
                ad = reader(a, resorts[slug])
                if not ad["id"]:
                    continue
                key = f"{platform[0]}{ad['id']}"
                old = ads.get(key)
                ad["first_seen"] = old["first_seen"] if old else d
                ad["last_seen"] = d
                ad["seen"] = (old["seen"] if old else 0) + 1; ad["v_first"] = old.get("v_first", old.get("versions")) if old else ad.get("versions")
                ads[key] = ad
    for ad in ads.values():
        last_run = latest_run.get((ad["p"], ad["slug"]), "")
        if ad["p"] == "meta":
            ad["live"] = ad["last_seen"] == last_run           # still in the most recent check of that resort
            ad["end"] = "" if ad["live"] else ad["last_seen"]
        else:
            ad["live"] = bool(ad["last_shown"]) and ad["last_shown"] >= (
                date.fromisoformat(last_run) - timedelta(days=3)).isoformat()
            ad["end"] = "" if ad["live"] else ad["last_shown"]
    return ads, latest_run


# ------------------------------------------------------------------ scoring and tags
KEYWORDS = [
    ("Season passes", r"season pass|\bpass(es)?\b|epic|ikon|indy pass|unlimited skiing|pass holder|passholder"),
    ("Lift tickets & packs", r"lift ticket|day ticket|tickets?\b|4-?pa[ck]k?|\bpak\b|frequent skier|lift access"),
    ("Lessons & learn-to", r"lesson|learn to|ski school|snowsports school|first[- ]timer|beginner|kids camp|private instruct"),
    ("Rentals & gear", r"rental|rent\b|demo|gear|tune|retail|\bshop\b"),
    ("Lodging & getaways", r"lodg|stay|night|hotel|condo|suite|room|getaway|vacation|resort package|slopeside"),
    ("Events & weddings", r"wedding|event|concert|festival|meeting|retreat|conference|race\b|competition|party"),
    ("Dining & après", r"dining|restaurant|après|apres|brunch|dinner|bar\b|brewery|menu"),
    ("Summer & activities", r"waterpark|aquatopia|zip ?line|golf|bike park|mountain bik|summer|tubing|coaster|spa\b|indoor"),
    ("Hiring", r"hiring|job|join (our|the) team|employment|career|work (at|for) "),
]
CTA_GUESS = {"book now": "Lodging & getaways", "shop now": "Lift tickets & packs", "get offer": "Lift tickets & packs",
             "apply now": "Hiring", "order now": "Season passes", "sign up": "Lessons & learn-to"}
PRICE = re.compile(r"\$\s?\d[\d,]*(?:\.\d\d)?")
MON = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def text_of(ad):
    return " ".join([ad.get("title", ""), ad.get("body", ""), ad.get("desc", ""), " ".join(ad.get("headlines", []))])


def find_deadline(text, ref):
    m = re.search(r"\b(?:by|before|ends?|until|thru|through|expires?|on sale through)\s+(?:on\s+|the\s+)?"
                  r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", text, re.I)
    if not m:
        return ""
    mo, dd = MON[m.group(1).lower()], int(m.group(2))
    y = int(ref[:4])
    try:
        d = date(y, mo, dd)
        if d.isoformat() < ref and (date.fromisoformat(ref) - d).days > 200:
            d = date(y + 1, mo, dd)
        return d.isoformat()
    except ValueError:
        return ""


def rule_tags(ad):
    t = text_of(ad).lower()
    camp = [c for c, rx in KEYWORDS if re.search(rx, t)]
    src = "copy"
    if not camp and ad.get("cta"):
        g = CTA_GUESS.get(ad["cta"].lower())
        camp, src = ([g], "button") if g else ([], "none")
    themes = []
    if PRICE.search(t) or re.search(r"\bsave\b|\d+% off|discount|deal|sale\b", t):
        themes.append("Discount")
    if re.search(r"kid|family|children", t):
        themes.append("Kids & family")
    if re.search(r"holiday|christmas|gift|black friday|cyber", t):
        themes.append("Gift & holiday")
    if re.search(r"powder|snow|inches|opening day|conditions", t):
        themes.append("Snow & conditions")
    dl = find_deadline(text_of(ad), ad.get("start") or date.today().isoformat())
    if dl:
        themes.append("Price deadline")
    return {"camp": camp[:2] or ["Brand & general"], "themes": themes, "prices": sorted(set(PRICE.findall(text_of(ad))))[:4],
            "deadline": dl, "offer": "", "src": src if camp else "none", "stand": "", "ai": False}


def days_live(ad, today):
    if ad["p"] == "google":
        span = ((date.fromisoformat(ad["last_shown"]) - date.fromisoformat(ad["start"])).days + 1
                if ad.get("last_shown") and ad.get("start") else 0)
        return max(ad.get("served_days") or 0, 0) or span
    end = date.fromisoformat(ad["end"]) if ad.get("end") else today
    return max(0, (end - date.fromisoformat(ad["start"])).days) if ad.get("start") else 0


def score(ads, today):
    """Winner score 0-100 from behaviour (see the site's '?' box): run length vs the resort's own normal
    (60), staying power (20), several versions (20). Under a week old -> None ('Too early')."""
    by = {}
    for a in ads:
        a["days"] = days_live(a, today)
        by.setdefault((a["p"], a["slug"]), []).append(a["days"])
    allmed = {p: median([a["days"] for a in ads if a["p"] == p] or [0]) for p in ("meta", "google")}
    for a in ads:
        L = by[(a["p"], a["slug"])]
        norm = median(L) if len(L) >= 4 else allmed[a["p"]]
        a["norm"] = round(norm)
        rel = a["days"] / max(norm, 7)
        if a["days"] < 7 and a["live"]:
            a["ws"], a["parts"] = None, None
            continue
        run = min(60, 30 * math.log2(1 + rel))
        stay = min(20, a["days"] / 90 * 20)
        ver = 20 if (a.get("versions") or 1) > 1 or a.get("dynamic") else 0
        a["parts"] = [round(run), round(stay), ver]
        a["ws"] = round(run + stay + ver)


# ------------------------------------------------------------------ output
def compact(a, tags, media):
    t = tags.get(a["key"]) or rule_tags(a)
    keep = ["id", "p", "slug", "n", "s", "rg", "start", "end", "live", "kind", "fmt", "versions", "title", "body",
            "desc", "cta", "link", "url", "days", "norm", "ws", "parts", "first_seen", "last_seen", "plats",
            "advertiser", "headlines", "regions", "surfaces", "served_days", "video_src", "vid", "img_l", "sig", "conf", "evergreen", "yt", "arc"]
    out = {k: a[k] for k in keep if k in a and a[k] not in ("", None, [], 0) or k in ("live", "ws")}
    if a["p"] == "meta":
        out.pop("video_src", None)                  # Meta video links expire within days; the ad library link stays
    out["key"] = a["key"]
    out["img"] = media.get(a["key"]) or ""
    out.update({k: t.get(k) for k in ("camp", "themes", "prices", "deadline", "offer", "src", "stand") if t.get(k)})
    out["camp"] = t.get("camp") or ["Brand & general"]
    if t.get("text") and not (out.get("title") or out.get("body")):
        out["seen_text"] = t["text"]                # words read off the image by the AI
    return out


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: "|".join(map(str, v)) if isinstance(v, list) else v for k, v in r.items()})


def build(now=None):
    now = now or datetime.now(timezone.utc)
    today = now.date()
    ads, latest_run = build_ads()
    for k, a in ads.items():
        a["key"] = k
    lst = list(ads.values())
    rstats = __import__("scoring").score_all(lst, today); __import__("archive").attach(lst)
    tags, media = load_json(TAGS, {}), load_json(MEDIA, {})
    out = [compact(a, tags, media) for a in lst]
    for mod, args in (("quality", (out,)), ("taxonomy", (out, tags))):  # health flags, then agency labels
        try:
            print(f"  {mod}:", __import__(mod).apply(*args))
        except Exception as e:
            print(f"  {mod} skipped:", str(e)[:200])
    out.sort(key=lambda a: (a.get("start") or ""), reverse=True)

    cols_common = ["id", "n", "slug", "kind", "fmt", "start", "end", "live", "days", "ws", "camp", "themes", "prices",
                   "deadline", "offer", "title", "body", "desc", "cta", "link", "url", "img", "first_seen", "last_seen", "obj", "aud", "ot", "fl", "sn", "health"]
    write_csv(os.path.join(DATA, "ads_meta.csv"), [a for a in out if a["p"] == "meta"],
              cols_common + ["versions", "plats"])
    write_csv(os.path.join(DATA, "ads_google.csv"), [a for a in out if a["p"] == "google"],
              cols_common + ["advertiser", "served_days", "headlines", "regions", "surfaces", "video_src"])

    reports = sorted(load_json(os.path.join(DOCS, "reports", "index.json"), []), key=lambda r: r["date"], reverse=True)
    resorts = [{"slug": r["slug"], "n": r["resort"], "s": r["state"], "rg": r["region"], "domain": r["domain"],
                "meta_page_id": r.get("meta_page_id", ""),
                "checked_meta": latest_run.get(("meta", r["slug"]), ""),
                "checked_google": latest_run.get(("google", r["slug"]), ""), "stats": rstats.get(r["slug"], {})} for r in load_resorts()]
    try:  # who buys each resort's media now; emails a switch the moment it shows up
        print("  agency:", __import__("agency").apply(lst, resorts, today))
    except Exception as e:
        print("  agency skipped:", str(e)[:200])
    lib = {"generated": now.strftime("%Y-%m-%d %H:%M UTC"), "today": today.isoformat(),
           "last_check": max(latest_run.values(), default=""), "health": __import__("archive").health(), "campaigns": CAMPAIGNS, "tax": __import__("taxonomy").LISTS,
           "resorts": resorts, "reports": reports, "ads": out}
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.LIB=" + json.dumps(lib, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"Library: {sum(a['p'] == 'meta' for a in out)} Meta ads ({sum(a['p'] == 'meta' and a['live'] for a in out)} live), "
          f"{sum(a['p'] == 'google' for a in out)} Google ads; {sum(1 for a in out if a['img'])} with saved images")
    return lst, out


if __name__ == "__main__":
    build()
