"""Winner score v2: which ads were most likely winners, adjusted for each resort's budget.

Neither Meta nor Google publishes spend or results, so the score reads what each resort reveals by how it
treats an ad. Run length alone over-rewards big-budget resorts (they can afford to leave everything running),
so run length only counts as much as that resort's habits make it meaningful, and most of the score comes
from comparisons that budget doesn't distort. Each signal is 0-1, then weighted:

  batch   Outlasted its launch batch (25): did it keep running after the resort's other ads launched within
          a week of it were switched off? Same resort, same budget, same moment.
  run     Run length vs the resort's own ads of the same kind (20 x informativeness). Informativeness drops
          for resorts that rarely switch ads off (low kill rate = big budget or set-and-forget).
  invest  Extra investment (20): versions / collation count, dynamic creative, versions added since first seen.
  steady  Steady serving (10, Google): share of days in its run that it was actually shown.
  reuse   Reused creative (15, bonus): same image or copy relaunched later, or used on the other platform.
  extend  Extended offer (10, bonus): kept running a week or more past the deadline in its own copy.

Bonus signals only count when present. Scores are pulled toward 50 when few signals are available, and each
ad gets a confidence level. Google ads shown over more than a year are marked always-on and capped at 70.
"""
import math
import os
import re
from datetime import date, timedelta
from statistics import median

W = {"batch": 25, "run": 20, "invest": 20, "steady": 10, "reuse": 15, "extend": 10}
CORE = ("batch", "run", "invest", "steady")


def iso(d):
    try:
        return date.fromisoformat(str(d)[:10]) if d else None
    except ValueError:
        return None


def days_live(ad, today):
    s = iso(ad.get("start"))
    if not s:
        return 0
    if ad["p"] == "google":
        last = iso(ad.get("last_shown"))
        span = (last - s).days + 1 if last else 0
        return max(ad.get("served_days") or 0, 0) or span
    end = iso(ad.get("end")) or today
    return max(0, (end - s).days)


def finish(ad, today):
    """When the ad stopped (today if it's still running)."""
    if ad["live"]:
        return today
    return iso(ad.get("end")) or iso(ad.get("last_shown")) or today


def kind_class(ad):
    return "text" if ad.get("kind") == "Text" else "creative"


def fingerprint(ad):
    if ad["p"] == "google" and ad.get("kind") == "Text":
        return ""  # templated search copy repeats for years; not a creative choice
    t = ((ad.get("title") or "") + " " + (ad.get("body") or "")).lower()
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9$% ]", "", t)).strip()
    return t[:160] if len(t) >= 25 else ""


def pct_rank(v, values):
    if len(values) < 3:
        return None
    below = sum(1 for x in values if x < v)
    same = sum(1 for x in values if x == v) - 1
    return (below + same / 2) / (len(values) - 1)


def informativeness(kill):
    """How much run length tells us at this resort. Unknown (fewer than 5 stopped ads) -> 0.6."""
    if kill is None:
        return 0.6
    return max(0.25, min(1.0, kill / 0.4))


def resort_stats(groups, today):
    recent = (today - timedelta(days=120)).isoformat()
    stats = {}
    for key, L in groups.items():
        ended = [a for a in L if not a["live"]]
        kill = sum(1 for a in ended if a["days"] <= 21) / len(ended) if len(ended) >= 5 else None
        active = sum(1 for a in L if a["live"] or (a.get("end") or a.get("last_shown") or "") >= recent)
        weeks = {iso(a["start"]).isocalendar()[:2] for a in L if (a.get("start") or "") >= recent and iso(a["start"])}
        stats[key] = {"ads": len(L), "active": active, "weeks": len(weeks),
                      "kill": None if kill is None else round(kill, 2),
                      "med": round(median([a["days"] for a in L])) if L else 0,
                      "info": round(informativeness(kill), 2)}
    for p in ("meta", "google"):
        ranked = sorted((s["active"], k) for k, s in stats.items() if k[0] == p)
        for i, (_, k) in enumerate(ranked):
            q = i / max(1, len(ranked) - 1)
            stats[k]["tier"] = "High" if q >= 0.67 else "Mid" if q >= 0.33 else "Low"
    return stats


def batch_signal(a, L, today):
    s = iso(a.get("start"))
    if not s:
        return None, ""
    fa = finish(a, today)
    wins, n, sibs = 0.0, 0, 0
    for b in L:
        sb = iso(b.get("start"))
        if b is a or not sb or abs((sb - s).days) > 7:
            continue
        sibs += 1
        if a["live"] and b["live"]:
            continue
        d = (fa - finish(b, today)).days
        n += 1
        wins += 1 if d > 3 else 0 if d < -3 else 0.5
    if not n:
        return None, (f"The {sibs} other ads launched within a week of it are all still running, so no result yet."
                      if sibs else "Launched on its own, so there's no batch to compare with.")
    return wins / n, f"Outlasted {wins:g} of {n} ads this resort launched within a week of it (ties count half)."


def invest_signal(a):
    v = a.get("versions") or 1
    s = 0.3 + 0.7 * min(1.0, math.log2(v) / 3)
    bits = [f"{v} versions" if v > 1 else "a single version"]
    if a.get("dynamic"):
        s = max(s, 0.65)
        bits.append("dynamic creative")
    vf = a.get("v_first") or v
    if a["p"] == "meta" and v > vf:
        s += 0.2
        bits.append(f"grew from {vf} versions since tracking first saw it")
    return min(1.0, s), ("Runs " if a["live"] else "Ran ") + ", ".join(bits) + ". More versions = more money and effort behind it."


def steady_signal(a):
    s0, last, served = iso(a.get("start")), iso(a.get("last_shown")), a.get("served_days") or 0
    if not s0 or not last or not served:
        return None, "Google didn't report days served."
    span = (last - s0).days + 1
    if span < 14:
        return None, "Too short a run to judge."
    return min(1.0, served / span), f"Shown on {served} of the {span} days between its first and last showing."


def extend_signal(a, dl, today):
    d, s0 = iso(dl), iso(a.get("start"))
    if not d or not s0 or d < s0:
        return None
    over = (finish(a, today) - d).days
    if over < 7:
        return None
    return 1.0, f"Kept running {over} days past the {d.strftime('%b %-d')} deadline in its own copy, so the offer was probably extended."


def reuse_map(ads, phash):
    """{ad key: {n, far, other}}: other ads from the same resort with the same copy or a near-identical picture."""
    by = {}
    for a in ads:
        by.setdefault(a["slug"], []).append(a)
    out = {}
    for L in by.values():
        info = []
        for a in L:
            h = phash.get(a["key"]) if kind_class(a) != "text" else None
            h = int(h, 16) if h else None
            if h is not None and not 4 <= h.bit_count() <= 60:
                h = None  # near-blank pictures all look alike
            info.append((a, fingerprint(a), h, iso(a.get("start"))))
        for i, (a, fa, ha, sa) in enumerate(info):
            for b, fb, hb, sb in info[i + 1:]:
                if a["p"] == b["p"] == "meta" and a.get("group") and a.get("group") == b.get("group"):
                    continue
                if not ((fa and fa == fb) or (ha is not None and hb is not None and (ha ^ hb).bit_count() <= 5)):
                    continue
                far = a["p"] != b["p"] or bool(sa and sb and abs((sa - sb).days) > 14)
                for x, y in ((a, b), (b, a)):
                    r = out.setdefault(x["key"], {"n": 0, "far": False, "other": False})
                    r["n"] += 1
                    r["far"] = r["far"] or far
                    r["other"] = r["other"] or x["p"] != y["p"]
    return out


def reuse_text(a, ru):
    s = "s" if ru["n"] > 1 else ""
    if ru["other"]:
        return f"The same image or copy also ran on {'Google' if a['p'] == 'meta' else 'Meta'}."
    if ru["far"]:
        return f"The same image or copy shows up in {ru['n']} other ad{s} launched at a different time, so the resort brought it back."
    return f"The same image or copy runs in {ru['n']} other ad{s} launched alongside it (copies across ad sets)."


def score(ads, today, phash=None, deadline=lambda a: ""):
    """Sets ws (0-100 or None), sig, conf, evergreen, days, norm on each ad. Returns {slug: {platform: stats}}."""
    for a in ads:
        a["days"] = days_live(a, today)
    groups = {}
    for a in ads:
        groups.setdefault((a["p"], a["slug"]), []).append(a)
    stats = resort_stats(groups, today)
    pool = {}
    for a in ads:
        pool.setdefault((a["p"], kind_class(a)), []).append(a["days"])
    reuse = reuse_map(ads, phash or {})
    out = {}
    for (p, slug), L in groups.items():
        rs = stats[(p, slug)]
        out.setdefault(slug, {})[p] = rs
        own = {}
        for b in L:
            own.setdefault(kind_class(b), []).append(b["days"])
        k = rs["kill"]
        habit = ("hasn't stopped enough ads yet to judge its habits" if k is None else
                 "rarely switches ads off" if k < 0.2 else "switches ads off often" if k >= 0.4 else "switches some ads off")
        for a in L:
            a["norm"] = rs["med"]
            a["sig"], a["conf"], a["evergreen"] = [], "", False
            if a["live"] and a["days"] < 7:
                a["ws"] = None
                continue
            sig = {"batch": batch_signal(a, L, today)}
            kc = kind_class(a)
            r, scope = (pct_rank(a["days"], own[kc]), "this resort's") if len(own[kc]) >= 4 else (None, "")
            if r is None:
                r, scope = pct_rank(a["days"], pool[(p, kc)]), "all tracked resorts'"
            if r is None:
                sig["run"] = (None, "Not enough ads to compare with yet.")
            else:
                txt = (f"{a['days']}d {'so far' if a['live'] else 'total'}, longer than {round(r * 100)}% of {scope} "
                       f"{'text ' if kc == 'text' else ''}ads on {p.title()} (typical {rs['med']}d). Counts "
                       f"{round(rs['info'] * 100)}% here: this resort {habit}.")
                dl = iso(deadline(a))
                if dl and not a["live"] and abs((finish(a, today) - dl).days) <= 5:
                    r = max(r, 0.6)
                    txt += " Stopped on the deadline in its own copy, so not penalised."
                sig["run"] = (r, txt)
            sig["invest"] = invest_signal(a)
            if p == "google":
                sig["steady"] = steady_signal(a)
            ru = reuse.get(a["key"])
            if ru:
                sig["reuse"] = (1.0 if ru["far"] else 0.5, reuse_text(a, ru))
            ex = extend_signal(a, deadline(a), today)
            if ex:
                sig["extend"] = ex
            w = dict(W, run=W["run"] * rs["info"])
            present = {key: v for key, (v, _) in sig.items() if v is not None}
            tw = sum(w[key] for key in present)
            if not tw:
                a["ws"] = None
                continue
            raw = sum(w[key] * v for key, v in present.items()) / tw
            core = sum(w[key] for key in present if key in CORE)
            full = W["batch"] + w["run"] + W["invest"] + (W["steady"] if p == "google" else 0)
            ws = 50 + (raw * 100 - 50) * min(1.0, core / (0.7 * full))
            s0, last = iso(a.get("start")), iso(a.get("last_shown"))
            if p == "google" and s0 and last and (last - s0).days > 365:
                a["evergreen"] = True
                ws = min(ws, 70)
            a["ws"] = max(0, min(100, round(ws)))
            n_core = sum(1 for key in present if key in CORE)
            a["conf"] = ("High" if "batch" in present and n_core >= 3 and (not a["live"] or a["days"] >= 30) else
                         "Medium" if n_core >= 3 or "batch" in present else "Low")
            a["sig"] = [[key, None if v is None else round(v * 100), round(w[key]), t] for key, (v, t) in sig.items()]
    return out


def score_all(ads, today):
    """Called by library.build: loads tags, picture fingerprints and saved media, then scores."""
    import library
    tags = library.load_json(library.TAGS, {})
    phash = library.load_json(os.path.join(library.DATA, "phash.json"), {})
    videos = library.load_json(os.path.join(library.DATA, "videos.json"), {})
    large = library.load_json(os.path.join(library.DATA, "media_large.json"), {})
    for a in ads:
        a["vid"] = videos.get(a["key"]) or ""
        a["img_l"] = large.get(a["key"]) or ""

    def deadline(a):
        t = tags.get(a["key"]) or library.rule_tags(a)
        return t.get("deadline") or ""

    return score(ads, today, phash, deadline)
