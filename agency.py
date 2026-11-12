"""Who buys each resort's media right now, kept current from the scraped ads, plus Ski Area Ad Atlas context.

Google's Ads Transparency Center names the verified advertiser that pays for every Google ad: the resort itself,
or the agency / freelancer buying its media. Meta doesn't disclose this for normal ads, so the buyer is read
from Google. Every build (library.build):
  - finds each resort's likely buyer now: the advertiser behind most of its Google ads shown in the last 60 days
  - compares with data/agency.json. A new advertiser with recent ads, or the old one going quiet while another
    takes over, is a switch: it is recorded on the site and emailed to ALERT_EMAIL straight away
  - adds a small 'Who buys the media' summary per resort to docs/data.js (shown by docs/buyer.js)
The first run only saves a baseline (no emails).
"""
import html
import json
import os
import re
from datetime import timedelta

import library

STATE = os.path.join(library.DATA, "agency.json")
ATLAS = os.path.join(library.DOCS, "atlas.html")
ALERT_EMAIL = "dean.isaac06@gmail.com"
SITE = "https://deanisaac06.github.io/Ski-Area-Ad-Tracking/"
RECENT_DAYS, NEW_DAYS = 60, 30
NL = chr(10)
KIND = {"resort": "the resort's own account", "agency": "agency", "person": "freelancer / individual", "other": "third party"}
CORP = r"\b(llc|inc|incorporated|corp|corporation|co|company|ltd|limited|lp|llp|plc|ulc|the|of|and|dba)\b"
GENERIC = {"ski", "skiing", "resort", "resorts", "mountain", "mountains", "mtn", "area", "areas", "valley", "lodge",
           "basin", "peak", "bowl", "snow", "club", "holdings", "group", "operating", "operations", "management",
           "sports", "recreation", "winter", "national", "lake", "lakes", "ridge", "hill", "hills", "www", "com"}
AGENCY = (r"media|marketing|agency|advertis|digital|creative|interactive|communications|strateg|partners|collective|"
          r"studio|consult|promotion|public relations|social|growth|performance|\blabs?\b|\bworks\b")

def nk(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").split("(")[0].lower())

def words(s):
    s = re.sub(CORP, " ", str(s or "").lower().replace("&", " "))
    return {w for w in re.findall(r"[a-z0-9]+", s) if len(w) >= 3 and w not in GENERIC}

def flat(v):
    if isinstance(v, list):
        return ", ".join(str(flat(x)) for x in v if x)
    if isinstance(v, dict):
        return str(v.get("n") or v.get("name") or "")
    return v

def atlas_index():
    try:
        with open(ATLAS, encoding="utf-8") as f:
            t = f.read()
        i = t.index("window.ATLAS=")
        rows = json.loads(t[i + 13:t.index("</script>", i)].strip().rstrip(";")).get("rows") or []
    except Exception as e:
        print("  agency: atlas not read:", str(e)[:120])
        rows = []
    idx = {}
    for x in rows:
        idx.setdefault(nk(x.get("n")) + "|" + str(x.get("s") or ""), x)
        idx.setdefault(nk(x.get("n")), x)
    return idx

def kind_of(name, r, ar):
    """resort (its own account), agency, person (freelancer) or other."""
    dom = nk(str(r.get("domain") or "").split(".")[0])
    own = words(r.get("n")) | words((ar or {}).get("o"))
    if words(name) & own or (len(dom) >= 5 and dom in nk(name)):
        return "resort"
    if re.search(AGENCY, name, re.I):
        return "agency"
    if not re.search(CORP, name.lower()) and re.fullmatch(r"[A-Za-z.' -]+", name) and 2 <= len(name.split()) <= 4:
        return "person"
    return "other"

def advertisers(L, recent):
    adv = {}
    for a in L:
        name = re.sub(r"\s+", " ", str(a.get("advertiser") or "")).strip()
        if not name:
            continue
        k = str(a.get("advertiser_id") or "").strip() or "n:" + nk(name)
        last = a.get("last_shown") or a.get("last_seen") or ""
        first = a.get("start") or a.get("first_seen") or ""
        v = adv.setdefault(k, {"id": k, "name": name, "n": 0, "recent": 0, "live": 0, "first": first, "last": "", "url": ""})
        v["n"] += 1
        v["recent"] += int(last >= recent)
        v["live"] += int(bool(a.get("live")))
        if first and (not v["first"] or first < v["first"]):
            v["first"] = first
        if last >= v["last"]:
            v["last"], v["name"], v["url"] = last, name, a.get("url") or v["url"]
    return adv

def K(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    return f"${v / 1000:.1f}M" if v >= 1000 else f"${round(v)}K"

def apply(ads, resorts, today):
    """ads: every ad from library.build_ads; resorts: the site's resort list. Adds r['buyer'] and emails switches."""
    idx = atlas_index()
    boot = not os.path.exists(STATE)
    st = library.load_json(STATE, {})
    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()
    fresh = (today - timedelta(days=NEW_DAYS)).isoformat()
    by = {}
    for a in ads:
        if a.get("p") == "google":
            by.setdefault(a.get("slug"), []).append(a)
    alerts = []
    for r in resorts:
        ar = idx.get(nk(r["n"]) + "|" + str(r.get("s") or "")) or idx.get(nk(r["n"]))
        adv = advertisers(by.get(r["slug"], []), recent)
        for v in adv.values():
            v["kind"] = kind_of(v["name"], r, ar)
        cur = max(adv.values(), key=lambda v: (v["recent"], v["live"], v["last"], v["n"]), default=None)
        s = st.get(r["slug"])
        if s is None:  # first time we see this resort: baseline, no email
            s = st[r["slug"]] = {"known": {k: v["name"] for k, v in adv.items()}, "current": cur["id"] if cur else "", "changes": []}
        else:
            known, prev = s.setdefault("known", {}), s.get("current") or ""
            old = adv.get(prev)
            told = set()

            def switch(v, still):
                ch = {"date": today.isoformat(), "from": known.get(prev, ""), "from_kind": old["kind"] if old else "",
                      "to": v["name"], "to_kind": v["kind"], "ads": v["n"], "first": v["first"], "url": v["url"], "still": still}
                s.setdefault("changes", []).append(ch)
                alerts.append((r, ch, ar))
                told.add(v["id"])

            for k, v in sorted(adv.items(), key=lambda kv: kv[1]["last"]):
                if k in known:
                    continue
                known[k] = v["name"]
                renamed = sum(nk(x) == nk(v["name"]) for x in known.values()) > 1  # same company, another Google account
                if v["last"] >= fresh and k != prev and not renamed:  # a brand-new advertiser with ads shown recently
                    switch(v, bool(old and old["last"] >= fresh))
            if (cur and prev and cur["id"] != prev and cur["id"] not in told and nk(cur["name"]) != nk(known.get(prev, "")) and cur["last"] >= fresh
                    and not (old and old["last"] >= fresh)):  # a known advertiser took over and the old one went quiet
                switch(cur, False)
            if cur:
                s["current"] = cur["id"]
        others = sorted((v for v in adv.values() if not cur or v["id"] != cur["id"]), key=lambda v: v["last"], reverse=True)[:4]
        pick = lambda v: {x: v[x] for x in ("name", "kind", "n", "recent", "live", "first", "last")}
        A = {k: flat(ar.get(k)) for k in ("o", "ot", "op", "ag", "ga", "st", "mm", "mml", "mmh") if ar and ar.get(k) not in (None, "", [])}
        r["buyer"] = {"cur": pick(cur) if cur else None, "others": [pick(v) for v in others],
                      "changes": (s.get("changes") or [])[-6:], "atlas": A}
    library.save_json(STATE, st, indent=1)
    sent = send(alerts) if alerts and not boot else False
    n = sum(1 for r in resorts if (r.get("buyer") or {}).get("cur"))
    return (f"{n} of {len(resorts)} resorts with a known media buyer; {len(alerts)} switch(es)"
            + (", email sent" if sent else "") + (" (first run: baseline saved, no emails)" if boot else ""))

def send(alerts):
    try:
        import mailer
    except Exception as e:
        print("  agency: mailer missing:", e)
        return False
    esc = lambda x: html.escape(str(x or ""))
    text, rich = [], []
    for r, ch, ar in alerts:
        frm = f"{ch['from']} ({KIND.get(ch['from_kind'], 'advertiser')})" if ch["from"] else "no earlier Google advertiser on record"
        to = f"{ch['to']} ({KIND.get(ch['to_kind'], 'advertiser')})"
        A = ar or {}
        ctx = " · ".join(x for x in (
            f"est. paid media {K(A.get('mm'))}/yr" if A.get("mm") is not None else "",
            f"owner {flat(A.get('o'))}" if A.get("o") else "",
            f"atlas says: {flat(A.get('st'))}" if A.get("st") else "",
            f"atlas agency: {flat(A.get('ag'))}" if A.get("ag") else "") if x)
        note = "The old advertiser is still running ads too, so this may be a handover in progress." if ch["still"] else ""
        rows = [f"From: {frm}", f"To: {to}", f"{ch['ads']} Google ad(s) under the new name, first shown {ch['first'] or 'recently'}",
                note, ctx and "Atlas context: " + ctx, ch["url"] and "Example ad: " + ch["url"]]
        rows = [x for x in rows if x]
        text.append(f"{r['n']} ({r.get('s', '')})" + NL + NL.join("  " + x for x in rows))
        rich.append(f"<h3 style='margin:16px 0 4px'>{esc(r['n'])} <span style='color:#666;font-weight:400'>{esc(r.get('s'))}</span></h3>"
                    f"<p style='margin:0'>From <b>{esc(frm)}</b><br>To <b>{esc(to)}</b></p>"
                    + "".join(f"<p style='margin:4px 0;color:#444'>{esc(x)}</p>" for x in rows[2:] if not x.startswith("Example ad: "))
                    + (f"<p style='margin:4px 0'><a href='{esc(ch['url'])}'>See the ad in Google's Ads Transparency Center</a></p>" if ch["url"] else ""))
    r0, c0 = alerts[0][0], alerts[0][1]
    subject = (f"Agency switch: {r0['n']} now buying through {c0['to']}" if len(alerts) == 1 else
               f"Agency switches: {len(alerts)} resorts changed who buys their Google ads")
    intro = "Spotted in the latest ad scrape: Google's verified advertiser changed for these resorts. The site is already updated."
    body = intro + NL + NL + (NL + NL).join(text) + NL + NL + SITE
    page = f"<p>{esc(intro)}</p>" + "".join(rich) + f"<p style='margin-top:18px'><a href='{SITE}'>Open the Resort Ad Library</a></p>"
    try:
        ok = mailer.send_email(subject, body, html=page, to=ALERT_EMAIL)
        print("  agency: switch email", ("sent to " + ALERT_EMAIL) if ok else "not sent (email not configured)")
        return ok
    except Exception as e:
        print("  agency: switch email failed:", str(e)[:200])
        return False
