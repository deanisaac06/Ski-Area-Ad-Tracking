"""Which resorts are tracked: the hand-picked ones in resorts.csv (pilot=yes) plus every ski area in the
Ski Area Ad Atlas (docs/atlas.html, about 275 areas across the US and Canada).

Each resort gets a check cadence (tier):
  weekly    the hand-picked resorts in resorts.csv (top prospects / potential clients) plus the
            TOP_SPENDERS biggest spenders in the atlas (estimated paid media)
  biweekly  everyone else (every 2 weeks)
To change one, add or edit its row in resorts.csv with pilot=yes and a tier column (weekly / biweekly).
Used by collect.py, library.py and cadence.py. Also writes data/roster.csv so the full list is easy to see.
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ATLAS = os.path.join(HERE, "docs", "atlas.html")
OUT = os.path.join(HERE, "data", "roster.csv")
TOP_SPENDERS = 10
PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK", "YT", "NT"}
COLS = ["slug", "resort", "state", "region", "country", "tier", "domain", "meta_page_id", "opportunity",
        "atlas_rank", "mm", "google_known", "source", "pilot", "owner", "pass"]
_cache = []


def nk(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").split("(")[0].lower())


def dom(s):
    s = re.sub(r"^https?://", "", str(s or "").strip().lower())
    return re.sub(r"^www[.]", "", s).split("/")[0]


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower().replace("'", "")).strip("-")


def num(v):
    try:
        return float(re.sub(r"[^0-9.-]", "", str(v)))
    except (TypeError, ValueError):
        return None


def atlas_rows():
    try:
        with open(ATLAS, encoding="utf-8") as f:
            t = f.read()
        i = t.index("window.ATLAS=")
        return json.loads(t[i + 13:t.index("</script>", i)].strip().rstrip(";")).get("rows") or []
    except Exception as e:
        print("  roster: atlas not read:", str(e)[:150])
        return []


def load():
    """Every tracked resort: the resorts.csv columns plus tier, country, mm (est. paid media), google_known."""
    if _cache:
        return [dict(r) for r in _cache]
    with open(os.path.join(HERE, "resorts.csv"), newline="", encoding="utf-8") as f:
        mine = [dict(r) for r in csv.DictReader(f) if r.get("pilot", "").strip().lower() == "yes"]
    rows = atlas_rows()
    spend = sorted((x for x in rows if num(x.get("mm"))), key=lambda x: -num(x.get("mm")))
    big = {nk(x.get("n")) + "|" + str(x.get("s") or "") for x in spend[:TOP_SPENDERS]}
    out, by_dom, by_name = [], {}, {}
    for r in mine:
        r["domain"] = dom(r.get("domain"))
        r["tier"] = (r.get("tier") or "weekly").strip().lower()
        r["source"] = "resorts.csv"
        out.append(r)
        if r["domain"]:
            by_dom[r["domain"]] = r
        by_name[nk(r.get("resort")) + "|" + str(r.get("state") or "")] = r
    for x in rows:
        st, d = str(x.get("s") or ""), dom(x.get("d"))
        key = nk(x.get("n")) + "|" + st
        r = (by_dom.get(d) if d else None) or by_name.get(key)
        if r is None:  # a new resort from the atlas
            r = {"resort": str(x.get("n") or "").strip(), "state": st, "domain": d,
                 "meta_page_id": str(x.get("mp") or "").strip(), "opportunity": str(x.get("op") or "")[:1],
                 "atlas_rank": str(x.get("rank") or ""), "pilot": "yes", "source": "atlas",
                 "tier": "weekly" if key in big else "biweekly"}
            if not r["resort"]:
                continue
            out.append(r)
            by_name[key] = r
            if d:
                by_dom[d] = r
        gc = num(x.get("gc"))
        r["region"] = r.get("region") or str(x.get("rg") or "")
        r["owner"] = r.get("owner") or str(x.get("o") or "")
        r["mm"] = x.get("mm") if x.get("mm") is not None else r.get("mm", "")
        r["google_known"] = "no" if gc == 0 else ("yes" if gc else r.get("google_known", ""))
        if not r.get("meta_page_id") and x.get("mp"):
            r["meta_page_id"] = str(x["mp"]).strip()
        if not r.get("domain") and d:
            r["domain"] = d
    try:  # Ikon, Epic and Indy's own ad accounts (passes.py), checked weekly like a top resort
        for acc in __import__("passes").ACCOUNTS:
            if not any(r.get("slug") == acc["slug"] for r in out):
                out.append({"slug": acc["slug"], "resort": acc["resort"], "state": "PASS", "region": "Passes",
                            "domain": acc["domain"], "meta_page_id": acc["meta_page_id"], "pilot": "yes",
                            "tier": "weekly", "source": "pass account", "google_known": "yes", "mm": "",
                            "opportunity": "", "atlas_rank": ""})
    except Exception as e:
        print(" roster: pass accounts not added:", str(e)[:120])
    names, seen = {}, set()
    for r in out:
        names[nk(r["resort"])] = names.get(nk(r["resort"]), 0) + 1
    for r in out:
        st = str(r.get("state") or "")
        r["region"] = r.get("region") or ("Canada" if st in PROVINCES else "West")
        r["country"] = "CA" if r["region"] == "Canada" or st in PROVINCES else "US"
        if r["tier"] not in ("weekly", "biweekly"):
            r["tier"] = "biweekly"
        if r["source"] == "atlas" and names[nk(r["resort"])] > 1 and "(" not in r["resort"]:
            r["resort"] = f"{r['resort']} ({st})"  # e.g. Crystal Mountain (WA) next to Crystal Mountain (MI)
        s = r.get("slug") or slugify(r["resort"].split("(")[0])
        if s in seen:
            s = slugify(r["resort"].split("(")[0] + "-" + st)
        r["slug"] = s
        seen.add(s)
    _cache[:] = out
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(out)
    except Exception as e:
        print("  roster: data/roster.csv not written:", str(e)[:120])
    return [dict(r) for r in out]


if __name__ == "__main__":
    L = load()
    print(len(L), "resorts:", sum(r["tier"] == "weekly" for r in L), "weekly,",
          sum(r["country"] == "CA" for r in L), "in Canada")
