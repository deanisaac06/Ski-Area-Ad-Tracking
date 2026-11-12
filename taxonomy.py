"""Agency-style labels for every ad, so the library can be searched the way a media team names campaigns.

  Product (line of business)  camp  set by ai.py, or the keyword rules in library.py
  Funnel stage                obj   Awareness (TOFU), Consideration (MOFU), Conversion (BOFU)
  Audience                    aud   who the ad speaks to
  Offer type                  ot    the kind of offer, if any
  Flight                      fl    the season window the ad launched in; sn is the ski season (e.g. 2026/27)

ai.py asks the AI for obj, aud and ot when it tags an ad; these rules fill in anything it hasn't reached yet,
so every ad has every label. Called by library.build().
"""
import re

FUNNEL = ["Awareness", "Consideration", "Conversion"]
AUDIENCES = ["Families & kids", "Beginners", "Pass holders & loyalty", "Locals & regional", "Destination travelers",
             "Groups & corporate", "Couples & adults", "Experts & core skiers", "Students & young adults",
             "Job seekers", "General audience"]
OFFER_TYPES = ["Early-bird deadline", "Price / discount", "Bundle / package", "Free / value-add", "Gift card",
               "Contest / giveaway", "No offer"]
FLIGHTS = ["Pre-season sales (Aug–Nov)", "Holiday (Dec–early Jan)", "Peak winter (Jan–Feb)", "Spring (Mar–Apr)",
           "Summer (May–Jul)"]
LISTS = {"funnel": FUNNEL, "audiences": AUDIENCES, "offers": OFFER_TYPES, "flights": FLIGHTS}

AUD_RX = [
    ("Families & kids", r"\bkids?\b|famil|children|\bchild\b|parent|little ones|youth"),
    ("Beginners", r"beginner|first[- ]?tim|learn to|never[- ]ever|new to (ski|snowboard)|lesson"),
    ("Pass holders & loyalty", r"pass ?holder|renew|loyal|\bmembers?\b|returning"),
    ("Locals & regional", r"\blocals?\b|in-state|resident|after work|night skiing|close to home|day trip|minutes from"),
    ("Destination travelers", r"getaway|vacation|lodging|hotel|\bstay\b|\bnights?\b|\btrip\b|escape|fly in"),
    ("Groups & corporate", r"\bgroups?\b|corporate|team building|meeting|conference|wedding|retreat"),
    ("Couples & adults", r"couple|romantic|date night|adults? only|21\+|\bspa\b|\bwine\b"),
    ("Experts & core skiers", r"expert|\bsteeps?\b|powder|backcountry|terrain park|black diamond|vertical|big mountain"),
    ("Students & young adults", r"college|student|young adult|under 30|\bteens?\b"),
    ("Job seekers", r"hiring|\bjobs?\b|careers?|join (our|the) team|employment"),
]
OFFER_RX = [
    ("Early-bird deadline", r"early[- ]?bird|prices? (go|going|will go) up|price increase|last chance|"
                            r"ends (soon|today|tonight|sunday)|before prices|lowest price"),
    ("Price / discount", r"\$\s?\d|\d+\s?% off|\bsave\b|savings|discount|\bdeals?\b|\bsale\b|half[- ]price"),
    ("Bundle / package", r"package|bundle|stay (and|&) ski|ski (and|&) stay|\bincludes?\b|combo|\d[- ]?pa[ck]k?\b"),
    ("Free / value-add", r"\bfree\b|complimentary|\bbonus\b|on us\b|at no (extra )?cost"),
    ("Gift card", r"gift card|gift certificate|e-?gift|stocking stuffer"),
    ("Contest / giveaway", r"giveaway|sweepstakes|contest|enter to win|win (a|an|free)\b|raffle"),
]
BUY_CTA = {"book now", "shop now", "buy now", "buy tickets", "get offer", "order now", "sign up", "apply now",
           "get tickets", "subscribe", "get quote", "reserve", "register", "get started", "call now"}
CONSIDER_CTA = {"learn more", "see menu", "get directions", "contact us", "see more", "view more", "explore",
                "visit website", "see details", "send message"}
BUY_WORDS = re.compile(r"\b(buy|book|reserve|order|register|shop|lock in|on sale|sign up|get yours|get your)\b")


def text(a):
    bits = [a.get(k) or "" for k in ("title", "body", "desc", "seen_text", "offer", "cta", "link")]
    return " ".join(bits + list(a.get("headlines") or [])).lower()


def offers(a, t):
    out = [name for name, rx in OFFER_RX if re.search(rx, t)]
    if a.get("deadline") and "Early-bird deadline" not in out:
        out.insert(0, "Early-bird deadline")
    return out[:2] or ["No offer"]


def audiences(a, t):
    out = [name for name, rx in AUD_RX if re.search(rx, t)]
    if "Hiring" in (a.get("camp") or []) and "Job seekers" not in out:
        out.insert(0, "Job seekers")
    return out[:3] or ["General audience"]


def funnel(a, t, ot):
    cta = (a.get("cta") or "").strip().lower()
    if cta in BUY_CTA or a.get("deadline") or a.get("prices") or "Early-bird deadline" in ot or "Price / discount" in ot:
        return "Conversion"
    if BUY_WORDS.search(t):
        return "Conversion"
    if cta in CONSIDER_CTA or ot != ["No offer"] or a.get("kind") == "Text":
        return "Consideration"
    return "Awareness"


def flight(d):
    if not d:
        return ""
    md = d[5:10]
    if md >= "12-01" or md <= "01-05":
        return FLIGHTS[1]
    if md <= "02-29":
        return FLIGHTS[2]
    if md <= "04-30":
        return FLIGHTS[3]
    if md <= "07-31":
        return FLIGHTS[4]
    return FLIGHTS[0]


def season(d):
    if not d:
        return ""
    y = int(d[:4]) - (0 if d[5:7] >= "08" else 1)
    return f"{y}/{(y + 1) % 100:02d}"


def apply(out, tags):
    """Adds obj, aud, ot, fl and sn (plus health, for the spreadsheets) to every ad going into data.js."""
    n = 0
    for a in out:
        a["fl"], a["sn"] = flight(a.get("start")), season(a.get("start"))
        if a.get("q"):
            a["health"] = a["q"].get("st", "")
        if a.get("gone"):
            continue
        tg = tags.get(a["key"]) or {}
        t = text(a)
        ot = [x for x in (tg.get("ot") or []) if x in OFFER_TYPES] or offers(a, t)
        aud = [x for x in (tg.get("aud") or []) if x in AUDIENCES] or audiences(a, t)
        obj = tg.get("obj") if tg.get("obj") in FUNNEL else funnel(a, t, ot)
        a.update(obj=obj, aud=aud[:3], ot=ot[:2])
        n += 1
    return f"{n} ads labelled"
