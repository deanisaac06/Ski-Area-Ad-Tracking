"""Ikon, Epic and Indy in the ad library. Rebuilt on every run from data already collected (no extra cost).

1. Pass push (ad field pp): each ad is read for a pass push - copy, headlines, words on the picture
   (data/vision.json), AI video notes, landing page address and title.
     "Ikon push"     the ad sells the pass: named in the headline, links to the pass site, or named next to
                     buying words (buy, price, deadline, lock in, renew...)
     "Ikon mention"  only named in passing, e.g. "Ikon Pass holders save 20%"
   Ads from the Ikon, Epic and Indy accounts themselves always count as a push.
2. Resort's pass (ad field rp, resort field pass), most trusted first: a "pass" column in resorts.csv
   (Ikon, Epic, Indy, Ikon+Indy or none), the atlas owner (Vail = Epic, Alterra = Ikon), the line-ups
   below (2024-25 season, may be out of date), then what the resort's own ads and landing pages say.
   If the line-up and strong evidence disagree, the evidence wins and the site says so.
3. Pass accounts (roster.py adds them, checked weekly): what each pass pushes now and which resorts
   amplify it (pass-push ads live or launched in the last 60 days).
"""
import json
import os
import re
from collections import Counter
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
PASSES = ["Epic", "Ikon", "Indy"]
ACCOUNTS = [
    {"slug": "ikon-pass", "resort": "Ikon Pass", "pass": "Ikon", "domain": "ikonpass.com", "meta_page_id": "1633142560076426"},
    {"slug": "epic-pass", "resort": "Epic Pass", "pass": "Epic", "domain": "epicpass.com", "meta_page_id": "1301903316522062"},
    {"slug": "indy-pass", "resort": "Indy Pass", "pass": "Indy", "domain": "indyskipass.com", "meta_page_id": "363269227836987"},
]
ACCOUNT_OF = {a["slug"]: a["pass"] for a in ACCOUNTS}
SITE = {"Ikon": "ikonpass.com", "Epic": "epicpass.com", "Indy": "indyskipass.com"}
NAME = {
    "Ikon": re.compile(r"\bikon\b|ikonpass", re.I),
    "Epic": re.compile(r"\bepic ?pass|epicpass|\bepic (?:day|local|military|nordic|college|kids|mountain rewards|mountain express|australia)\b|\bmy ?epic\b", re.I),
    "Indy": re.compile(r"\bindy ?(?:ski ?)?pass|indyskipass|\bindy ?\+|\bindy (?:base|plus|xc)\b", re.I),
}
BUY = re.compile(r"\bbuy|purchase|price|\$ ?\d|deadline|last chance|on sale|lock in|renew|starting at|before|"
                 r"get (?:your|the|an?) |ends? |\bsale\b|save up to|unlock", re.I)
HOLDER = re.compile(r"^[\s\w]{0,12}?(?:holders?|members?)", re.I)
NEG = re.compile(r"not (?:be )?(?:accepted|valid|included|honou?red)|n.t accept|not (?:on|part of) the", re.I)
OWNER = [(re.compile(r"\bvail\b", re.I), "Epic"), (re.compile(r"alterra", re.I), "Ikon")]
SUFFIX = ("skiandsnowboardresort", "mountainresort", "skiresort", "skiarea", "resort", "mountain")
# 2024-25 line-ups (US + Canada, the well-known members). name|ST = only in that state. Evidence can override.
LINEUP = {
    "Epic": "vail beavercreek breckenridge keystone crestedbutte parkcity heavenly northstar kirkwood stevenspass "
            "whistler stowe okemo mtsnow mtsunapee sunapee attitash wildcat|NH crotched hunter liberty|PA roundtop "
            "whitetail jackfrost bigboulder sevensprings hiddenvalley|PA hiddenvalley|MO laurel|PA aftonalps "
            "mtbrighton wilmot alpinevalley|OH bostonmills brandywine madriver|OH snowcreek|MO paolipeaks "
            "fernie kickinghorse kimberley nakiska mtsainteanne stoneham",
    "Ikon": "steamboat winterpark palisadestahoe palisades mammoth june|CA bigbear bearmountain snowsummit "
            "snowshoe|WV stratton sugarbush tremblant mttremblant blue|ON solitude crystal|WA deervalley aspen "
            "aspensnowmass aspenhighlands snowmass jacksonhole bigsky alta|UT snowbird brighton|UT taos|NM "
            "arapahoebasin abasin copper eldora revelstoke banffsunshine sunshinevillage lakelouise norquay "
            "mtnorquay red|BC cypress mtbachelor schweitzer summitatsnoqualmie snoqualmie boyne highlands|MI "
            "boynemountainthehighlands boynemountainandthehighlands killington pico sundayriver sugarloaf "
            "loon|NH windham camelback mthoodmeadows lemassif lemassifdecharlevoix sunvalley snowbasin",
    "Indy": "jaypeak magic|VT boltonvalley saddleback blackmountain|NH black|NH berkshireeast catamount whitepass "
            "bluewood louploup 49degreesnorth hoodoo mtashland sunlight cooper|CO eaglecrest crystal|MI caberfae",
}

def norm(n):
    k = re.sub(r"[^a-z0-9]", "", str(n or "").split("(")[0].lower().replace("&", "and"))
    k = re.sub(r"^(?:mount|mont)(?=[a-z])", "mt", k)
    k = re.sub(r"^(?:the|ski)(?=[a-z]{4})", "", k)
    changed = True
    while changed:
        changed = False
        for s in SUFFIX:
            if k.endswith(s) and len(k) > len(s) + 2:
                k, changed = k[:-len(s)], True
    return k

def lineup_table():
    out = []
    for p, words in LINEUP.items():
        for w in words.split():
            name, _, st = w.partition("|")
            out.append((norm(name), st, p))
    return out

def lineup_pass(r, table):
    keys = {norm(r.get("resort")), norm(str(r.get("slug") or "").replace("-", " "))} - {""}
    st, hit = str(r.get("state") or ""), []
    for a, s, p in table:
        if (s and s != st) or p in hit:
            continue
        if any(k == a or (len(a) >= 6 and k.startswith(a)) for k in keys):
            hit.append(p)
    return hit

# ------------------------------------------------------------------ pass push on each ad
def load_vision():
    try:
        with open(os.path.join(HERE, "data", "vision.json")) as f:
            v = json.load(f)
        fp = v.get("fp") or {}
        return {k: str((fp.get(e.get("fp")) or {}).get("t") or "") for k, e in (v.get("ads") or {}).items()
                if isinstance(e, dict)}
    except Exception:
        return {}

def read_ad(a, words):
    arc = a.get("arc") or {}
    note, lp = arc.get("note") or {}, arc.get("lp") or {}
    head = " ".join([a.get("title") or "", " ".join(a.get("headlines") or []), a.get("offer") or "",
                     note.get("offer") or "", (a.get("body") or "")[:90]])
    rest = " ".join([a.get("body") or "", a.get("desc") or "", a.get("seen_text") or "", words.get(a.get("key"), ""),
                     note.get("summary") or "", note.get("onscreen") or "", note.get("voiceover") or "", a.get("cta") or ""])
    url = " ".join([a.get("link") or "", lp.get("u") or "", lp.get("t") or ""]).lower()
    return head, rest, url

def strength(text, rx):
    best = ""
    for m in rx.finditer(text):
        if BUY.search(text[max(0, m.start() - 70):m.end() + 70]) and not HOLDER.search(text[m.end():m.end() + 25]):
            return "push"
        best = "mention"
    return best

def classify(a, words):
    acc = ACCOUNT_OF.get(a.get("slug"))
    if acc:
        return [acc + " push"]
    head, rest, url = read_ad(a, words)
    allt = head + " " + rest
    out = []
    for p in PASSES:
        rx = NAME[p]
        s = strength(allt, rx)
        if SITE[p] in url or rx.search(url):
            s = "push"
        elif s == "mention" and rx.search(head) and not any(HOLDER.search(head[m.end():m.end() + 25]) for m in rx.finditer(head)):
            s = "push"
        if s == "mention" and NEG.search(allt):
            s = ""
        if s:
            out.append(p + " " + s)
    return out

# ------------------------------------------------------------------ which pass each resort is on
def site_votes(ads_of):
    seen, votes = set(), Counter()
    for a in ads_of:
        path = ((a.get("arc") or {}).get("lp") or {}).get("txt")
        if not path or path in seen or len(seen) >= 25:
            continue
        seen.add(path)
        try:
            with open(os.path.join(DOCS, path), encoding="utf-8") as f:
                t = " ".join(x for x in f.read().splitlines() if not NEG.search(x))
        except Exception:
            continue
        for p in PASSES:
            if NAME[p].search(t):
                votes[p] += 1
    return votes

def decide(r, table, ev):
    own = str(r.get("pass") or "").strip()
    if own:
        return [p for p in PASSES if p.lower() in own.lower()], "set in resorts.csv"
    for rx, p in OWNER:
        if rx.search(str(r.get("owner") or "")):
            return [p], "owned by " + str(r.get("owner"))
    top = ev.most_common()
    strong = top[0][0] if top and top[0][1] >= 2 and (len(top) == 1 or top[0][1] >= 2 * top[1][1]) else ""
    known = lineup_pass(r, table)
    if known:
        if strong and strong not in known and ev[strong] >= 3 and not any(ev[k] for k in known):
            return [strong], "seen in its ads and site (2024-25 line-up said " + "/".join(known) + ")"
        return known, "2024-25 pass line-up" + (", confirmed by its ads and site" if any(ev[k] for k in known) else "")
    if strong:
        return [strong], "seen in its ads and site"
    return [], "no sign of Epic, Ikon or Indy in its ads or site"

def apply(out, resorts):
    """Adds pp (pass push) and rp (resort's pass) to every ad, and a pass summary to every resort."""
    import roster
    words, table = load_vision(), lineup_table()
    full = {r["slug"]: r for r in roster.load()}
    by = {}
    for a in out:
        pp = classify(a, words)
        if pp:
            a["pp"] = pp
        else:
            a.pop("pp", None)
        by.setdefault(a.get("slug"), []).append(a)
    today = date.today()
    since, week = (today - timedelta(days=60)).isoformat(), (today - timedelta(days=7)).isoformat()
    is_push = lambda a, p=None: any(x.endswith("push") and (not p or x.startswith(p)) for x in a.get("pp", []))
    on_count = Counter()
    for r in resorts:
        allads = by.get(r["slug"], [])
        ads_of = [a for a in allads if not a.get("gone")]
        if ACCOUNT_OF.get(r["slug"]):
            for a in allads:
                a["rp"] = ["Pass account"]
            continue
        ev = site_votes(ads_of)
        ev.update(x.split()[0] for a in ads_of for x in a.get("pp", []))
        on, src = decide(full.get(r["slug"], r), table, ev)
        pushed = [a for a in ads_of if is_push(a)]
        r["pass"] = {"on": on, "src": src, "ads": len(ads_of),
                     "push": dict(Counter(x.split()[0] for a in ads_of for x in a.get("pp", []) if x.endswith("push"))),
                     "mention": dict(Counter(x.split()[0] for a in ads_of for x in a.get("pp", []) if x.endswith("mention"))),
                     "live": sum(1 for a in pushed if a.get("live")),
                     "last": max((a.get("start") or "" for a in pushed), default="")}
        for p in on:
            on_count[p] += 1
        for a in allads:
            a["rp"] = on or ["None of these"]
    for r in resorts:  # the pass accounts: what each pushes, who amplifies it
        acc = ACCOUNT_OF.get(r["slug"])
        if not acc:
            continue
        mine = [a for a in by.get(r["slug"], []) if not a.get("gone")]
        live = [a for a in mine if a.get("live")]
        mix = Counter((a.get("camp") or ["Brand & general"])[0] for a in (live or mine))
        offers = Counter(a["offer"] for a in (live or mine) if a.get("offer"))
        amp = []
        for x in resorts:
            if ACCOUNT_OF.get(x["slug"]):
                continue
            hits = [a for a in by.get(x["slug"], []) if not a.get("gone") and is_push(a, acc)
                    and (a.get("live") or (a.get("start") or "") >= since)]
            if hits:
                amp.append({"n": x["n"], "c": len(hits), "live": sum(1 for a in hits if a.get("live")),
                            "last": max(a.get("start") or "" for a in hits),
                            "on": acc in ((x.get("pass") or {}).get("on") or [])})
        amp.sort(key=lambda z: (-z["c"], z["n"]))
        r["pass"] = {"account": acc, "ads": len(mine), "live": len(live),
                     "new7": sum(1 for a in mine if (a.get("start") or "") >= week),
                     "mix": mix.most_common(5), "offers": [o for o, _ in offers.most_common(4)],
                     "deadlines": sorted({a["deadline"] for a in live if a.get("deadline") and a["deadline"] >= today.isoformat()})[:4],
                     "amp": amp[:15], "amp_n": len(amp), "on_n": on_count[acc]}
    n = sum(1 for a in out if is_push(a) and not ACCOUNT_OF.get(a.get("slug")))
    return (f"{n} resort ads push a pass; resorts on Epic {on_count['Epic']}, Ikon {on_count['Ikon']}, "
            f"Indy {on_count['Indy']}")
