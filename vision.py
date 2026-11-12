"""Content check: is the saved picture really the ad, or a placeholder that slipped through?

Runs at the start of every ad health check (quality.run), so new ads are checked as they come in.
1. Free checks on every saved picture, every run:
   icon    only a logo or map pin was saved (200px or smaller, roughly square)
   blank   a light page with only a speck on it (a broken-image icon, a stray logo)
   shared  the identical picture is filed under ads from two or more resorts: a Google error page or
           empty template, never a real creative
   known   the same picture as an ad already confirmed broken
2. An AI look (same Gemini / Groq / Cloudflare keys as the tags) at each distinct picture not looked at yet,
   suspects first: no copy, no button or landing page, Google Maps placements, thin or tiny pictures, little
   detail. Results are kept by picture fingerprint, so a placeholder seen 20 times costs one look.
quality.py then repairs the ad, shows it as copy only, or sets it aside as unavailable, as before.

data/vision.json {"fp": {fingerprint: {"v": verdict, "t": words seen}}, "bad": {fingerprint: verdict},
                  "ads": {ad key: {"v": verdict, "how": how it was spotted, "fp": fingerprint}}}
Run: python vision.py
"""
import base64
import os
import time
from collections import defaultdict
from datetime import date

from PIL import Image

import library
import media

VISION = os.path.join(library.DATA, "vision.json")
BAD = ("error", "blank", "template", "broken", "icon")
BATCH, MAX_CALLS, MAX_SECONDS = 5, 30, 600  # 5 pictures per call: Groq's limit if it has to take over

PROMPT = """These are saved previews of ski resort ads from the Meta and Google ad libraries. Some previews failed
to capture the ad. For EACH image return one JSON object:
- "k": the label shown before the image, copied exactly
- "v": ONE of
  "ad": a real ad - a photo, a designed graphic, a video frame, or a search / text ad with real words
  "error": an error page or message (500, 404, "That's an error", "Something went wrong", "not available")
  "blank": empty or nearly empty - a flat colour, a white page, only a spinner or a broken-image icon
  "template": an unfilled template - placeholders in angle brackets like <Rating (Reviews)>, <Category>,
    <Open Hours>, <Distance>, or grey bars where the words should be
  "broken": the main photo is missing - a broken-image icon or alt text such as "Photo of ..." in its place
  "icon": only a logo, app icon or map pin, with no ad message
- "t": the main words on the image, under 15 words
If unsure whether it is a real ad, answer "ad".
Return JSON only: {"items": [ ... ]}"""

_POOL = None

def ham(a, b):
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return 64

def near(fp, pool, d=3):
    """The verdict of a known-broken picture within d bits of this fingerprint, else ''."""
    if fp in pool:
        return pool[fp]
    return next((v for x, v in pool.items() if ham(fp, x) <= d), "")

def speck(im):
    """True for a light, flat page whose only content sits in a small patch (a broken-image icon, a stray logo)."""
    w, h = im.size
    g = im.convert("L").resize((64, max(1, round(64 * h / w))))
    sw, sh = g.size
    corners = [g.getpixel(p) for p in ((0, 0), (sw - 1, 0), (0, sh - 1), (sw - 1, sh - 1))]
    bg = max(set(corners), key=corners.count)
    if bg < 200:
        return False
    box = g.point(lambda v: 255 if abs(v - bg) > 18 else 0).getbbox()
    if not box:
        return True
    return (box[2] - box[0]) * (box[3] - box[1]) < 0.06 * sw * sh

def local(im):
    """(verdict, how) from the picture alone, or ('', '')."""
    w, h = im.size
    if max(w, h) <= 200 and 0.75 <= w / float(h) <= 1.33:
        return "icon", "only a small logo or icon was saved"
    if speck(im):
        return "blank", "a white page with almost nothing on it"
    return "", ""

def bad_picture(im):
    """Used by quality.repair: a verdict when a replacement picture is itself a placeholder, else ''."""
    global _POOL
    if _POOL is None:
        _POOL = library.load_json(VISION, {}).get("bad") or {}
    v, _ = local(im)
    return v or near(media.dhash(im), _POOL)

def suspicion(a, w, h, size):
    """How likely the picture isn't the real ad, from the ad's other data points (higher = look first)."""
    s = 0
    if not (a.get("title") or a.get("body") or a.get("headlines")):
        s += 2  # no copy captured
    if not (a.get("cta") or a.get("link")):
        s += 1  # no button or landing page
    if "Google Maps" in (a.get("surfaces") or []):
        s += 2  # Maps placements are where Google's previews break most
    if max(w, h) <= 240 or h < w * 0.35:
        s += 2  # tiny or a thin strip
    if size < w * h * 0.06:
        s += 1  # very little detail for its size
    return s

def ask_ai(batch, deadline):
    """({fingerprint: {"v", "t"}}, provider) for up to BATCH (fingerprint, path) pairs; None when no answer."""
    import ai
    parts, labels = [{"text": PROMPT}], {}
    for i, (fp, path) in enumerate(batch):
        label = "p" + str(i + 1)
        labels[label] = fp
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        parts += [{"text": label + ":"}, {"inline_data": {"mime_type": "image/jpeg", "data": data}}]
    text, prov = ai.router().ask(parts, deadline, json_out=True, gemini_models=ai.TAG_MODELS)
    if not text:
        return None, prov
    got = {}
    for d in ai.parse(text):
        fp = labels.get(str(d.get("k")).strip().strip(":").lower())
        v = str(d.get("v") or "").strip().lower()
        if fp and (v == "ad" or v in BAD):
            got[fp] = {"v": v, "t": str(d.get("t") or "")[:120]}
    return got, prov

def run(max_calls=MAX_CALLS, max_seconds=MAX_SECONDS):
    """Checks every saved picture; returns {ad key: {"v": verdict, "how": ..., "fp": ...}} for the ones that aren't the ad."""
    ads, _ = library.build_ads()
    saved = library.load_json(library.MEDIA, {})
    q = library.load_json(os.path.join(library.DATA, "quality.json"), {})
    vs = library.load_json(VISION, {})
    fpv, bad = vs.get("fp") or {}, vs.get("bad") or {}
    rows = []
    for k, a in ads.items():
        rel = saved.get(k)
        if not isinstance(rel, str) or not rel:
            continue
        path = os.path.join(library.DOCS, rel)
        try:
            with Image.open(path) as im:
                im = media.to_rgb(im)
                v, how = local(im)
                rows.append({"k": k, "a": a, "fp": media.dhash(im), "path": path, "w": im.size[0], "h": im.size[1],
                             "size": os.path.getsize(path), "v": v, "how": how})
        except Exception:
            continue
    # pictures quality.py already found broken teach the check what placeholders look like
    for r in rows:
        rec = q.get(r["k"]) or {}
        if rec.get("p") in ("blank", "collapsed"):
            bad.setdefault(r["fp"], "blank")
        elif rec.get("why") == "error" and rec.get("st") in ("text", "gone") and not (r["a"].get("title") or r["a"].get("body")):
            bad.setdefault(r["fp"], "error")
    resorts = defaultdict(set)
    for r in rows:
        resorts[r["fp"]].add(r["a"]["slug"])

    # an AI look at each distinct picture not looked at yet: shared pictures and suspects first, then newest
    rows.sort(key=lambda r: r["a"].get("start") or "", reverse=True)
    rows.sort(key=lambda r: (len(resorts[r["fp"]]) < 2, -suspicion(r["a"], r["w"], r["h"], r["size"])))
    todo, queued = [], set()
    for r in rows:
        if not r["v"] and r["fp"] not in fpv and r["fp"] not in queued:
            queued.add(r["fp"])
            todo.append((r["fp"], r["path"]))
    looked, calls, deadline = 0, 0, time.time() + max_seconds
    try:
        import ai
        ready = ai.router().any_provider()
    except Exception as e:
        print(" content check: AI not available:", str(e)[:100])
        ready = False
    while ready and todo and calls < max_calls and time.time() < deadline - 60:
        batch, todo = todo[:BATCH], todo[BATCH:]
        calls += 1
        try:
            got, prov = ask_ai(batch, deadline)
        except Exception as e:
            print(" content check: AI call failed:", str(e)[:120])
            got, prov = None, None
        if got is None:
            todo = batch + todo
            break
        fpv.update(got)
        looked += len(got)
        time.sleep(6.5)
    for fp, r in fpv.items():
        if r.get("v") in BAD:
            bad[fp] = r["v"]
    # verdicts: the picture itself, then the AI, then known-broken pictures, then pictures shared across resorts
    out, n = {}, defaultdict(int)
    for r in rows:
        fp, v, how = r["fp"], r["v"], r["how"]
        seen = fpv.get(fp) or {}
        if not v and seen.get("v") in BAD:
            v, how = seen["v"], "AI look at the saved picture" + (" (" + seen["t"] + ")" if seen.get("t") else "")
        elif not v and seen.get("v") != "ad":
            known = near(fp, bad)
            if known:
                v, how = known, "same picture as an ad already found broken"
            elif len(resorts[fp]) > 1:
                v, how = "shared", "same picture filed under " + str(len(resorts[fp])) + " different resorts"
        if v:
            out[r["k"]] = {"v": v, "how": how, "fp": fp}
            n[v] += 1
    vs.update({"fp": fpv, "bad": bad, "ads": out, "checked": date.today().isoformat()})
    library.save_json(VISION, vs)
    line = (f"Content check: {len(rows)} pictures, {looked} looked at by AI this run ({len(todo)} waiting), "
            f"{len(out)} are not the real ad: " + (", ".join(f"{c} {v}" for v, c in sorted(n.items())) or "none"))
    print(line)
    sm = os.environ.get("GITHUB_STEP_SUMMARY")
    if sm:
        with open(sm, "a") as f:
            f.write(chr(10) + "### Content check" + chr(10) + line + chr(10))
    return out

if __name__ == "__main__":
    run()
