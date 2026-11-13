"""Ad health check: flags ads that come in broken, tries a simple fix, and sets aside the ones it can't fix.

Broken means the saved picture is:
    error      an error page instead of the ad (Google "500. That's an error.", 404 / Not Found, ...)
    blank      an empty picture (one flat colour, or almost nothing on it)
    collapsed  a template that rendered as a thin strip with no real content
    missing    the picture link was dead, or the saved file is gone or unreadable
    empty      nothing was captured at all: no picture, no copy, no video

The simple fix (needs the network, so it runs in run(), up to 3 tries per ad across runs):
    1. another picture of the same ad: saved YouTube frames, the YouTube cover frame, a saved carousel card or
       version, the other picture links in the download, then the original link once more
    2. no good picture, but the ad has copy or a playable video: the broken picture is dropped and the site shows
       the copy (status "text")
    3. otherwise the ad is set aside (status "gone"): the site lists it under "Unavailable" with what we know
       (resort, platform, format, dates, advertiser) and why, and leaves it out of the normal views and counts.

data/quality.json  {ad key: {"st": ok|fixed|text|gone, "why": reason, "src": what fixed it, "d": date flagged,
                             "tries": n, "p": picture check result, "f": file signature, "w": width, "h": height}}
Run: python quality.py
"""
import io
import os
import re
import subprocess
import tempfile
from collections import Counter
from datetime import date

import requests
from PIL import Image, ImageStat

import library
import media

QUAL = os.path.join(library.DATA, "quality.json")
MAX_TRIES = 3
ERR_TEXT = re.compile(
    r"that.s an error|that.s all we know|\berror\s*(?:code\s*)?\d{3}\b|"
    r"\b(?:400|403|404|410|429|500|502|503|504)\b\W{0,3}(?:that|error|not found|bad request|forbidden|server|service)|"
    r"<(?:rating|category|open hours|distance)[ >]|page not found|not found on this server|internal server error|service unavailable|bad gateway|"
    r"something went wrong|please try again later|ad (?:is )?(?:not|no longer) available|"
    r"this ad (?:was|has been) removed|content (?:is )?(?:currently )?unavailable|access denied|request blocked", re.I)
REASON = {
    "error": "An error page came back instead of the ad when it was collected",
    "blank": "The ad preview came back blank",
    "collapsed": "The ad template rendered collapsed, with no real content",
    "missing": "The ad's picture link was dead (404) and no other copy could be found",
    "empty": "Nothing about the ad was captured beyond its dates",
    "template": "Google sent an empty ad template (placeholders like <Rating>, no real content)",
    "broken": "The ad's preview came back without its main picture",
    "icon": "Only a logo or map pin came back, not the ad itself",
    "shared": "The saved picture is a Google placeholder that also shows up under other resorts' ads",
}

def inspect(im):
    """'' if the picture looks like a real ad, else blank / collapsed."""
    w, h = im.size
    if w < 24 or h < 24 or h < w * 0.12 or w < h * 0.12:
        return "collapsed"
    sw, sh = (96, max(1, round(96 * h / w))) if w >= h else (max(1, round(96 * w / h)), 96)
    g = im.convert("L").resize((sw, sh))
    if ImageStat.Stat(g).stddev[0] < 4:
        return "blank"
    corners = [g.getpixel(p) for p in ((0, 0), (sw - 1, 0), (0, sh - 1), (sw - 1, sh - 1))]
    bg = max(set(corners), key=corners.count)
    mask = g.point(lambda v: 255 if abs(v - bg) > 18 else 0)
    ink = mask.histogram()[255] / float(sw * sh)
    if ink < 0.015:
        return "blank"
    box = mask.getbbox()
    if box and (box[3] - box[1]) < sh * 0.08 and ink < 0.04:
        return "collapsed"
    if h < w * 0.3 and bg > 200 and ink < 0.12:
        return "collapsed"  # a short, mostly white strip: usually an error banner or an empty template
    return ""

def sig(path):
    try:
        s = os.stat(path)
        return f"{s.st_size}-{int(s.st_mtime)}"
    except OSError:
        return ""

def check_file(rel):
    """(problem, width, height) for a saved picture under docs/."""
    try:
        with Image.open(os.path.join(library.DOCS, rel)) as im:
            im = media.to_rgb(im)
            return inspect(im), im.size[0], im.size[1]
    except Exception:
        return "missing", 0, 0

VIDS = {}  # saved Meta videos (media.py), so a blank preview can be swapped for a frame of the video
VIS = {}  # vision.py's content check for this run: {ad key: {"v": verdict, "how": ..., "fp": ...}}

def seen(k):
    """The content check's verdict for the ad's saved picture ('' when it looked like the real ad)."""
    return (VIS.get(k) or {}).get("v", "")

def bad_pic(im):
    """A verdict when a replacement picture is itself a placeholder, else ''."""
    try:
        return __import__("vision").bad_picture(im)
    except Exception:
        return ""

def bad_text(s):
    return bool(s) and bool(ERR_TEXT.search(s))

def has_copy(a):
    txt = " ".join([a.get("title") or "", a.get("body") or ""] + list(a.get("headlines") or []))
    return bool(txt.strip()) and not bad_text(txt)

def examine(k, a, rel, tags, rec, failed):
    """(problem, record) for one ad; picture checks are cached by file signature."""
    read = (tags.get(k) or {}).get("text") or ""
    if bad_text(read) or bad_text((a.get("title") or "") + " " + (a.get("body") or "")):
        txt_prob = "error"
    else:
        txt_prob = ""
    out = {k2: rec[k2] for k2 in ("st", "why", "src", "d", "tries") if k2 in rec}
    if rel:
        f = sig(os.path.join(library.DOCS, rel))
        if f and rec.get("f") == f and "p" in rec:
            p, w, h = rec["p"], rec.get("w", 0), rec.get("h", 0)
        else:
            p, w, h = check_file(rel)
        out.update({"p": p, "f": f, "w": w, "h": h})
        return txt_prob or p or seen(k), out
    if a.get("img_src") and failed.get(k, 0) < 3:
        return None, out  # media.py is still trying to download it
    if a.get("img_src"):
        return txt_prob or "missing", out
    if txt_prob:
        return txt_prob, out
    if not has_copy(a) and not a.get("yt") and not a.get("video_src"):
        return "empty", out
    return "", out  # a text ad with no picture: normal

def candidates(a):
    """Other pictures of the same ad, best first: (label, local path or URL)."""
    out = []
    arc = a.get("arc") or {}
    for rel in arc.get("frames") or []:
        out.append(("saved YouTube frame", ("local", rel)))
    if a.get("yt"):
        for n in ("maxresdefault", "sddefault", "hqdefault"):
            out.append(("YouTube cover frame", f"https://i.ytimg.com/vi/{a['yt']}/{n}.jpg"))
    v = VIDS.get(a.get("key"))
    if isinstance(v, str):
        for t in (1, 3, 6, 0):
            out.append(("frame from the ad's video", ("frame", os.path.join(library.DOCS, v), t)))
    elif a.get("video_src"):
        out.append(("frame from the ad's video", ("frame", a["video_src"], 1)))
    for rel in arc.get("cards") or []:
        out.append(("saved card / version", ("local", rel)))
    for u in a.get("cards_src") or []:
        if isinstance(u, str) and u.startswith("http") and u != a.get("img_src"):
            out.append(("another version's picture", u))
    if a.get("img_src"):
        out.append(("original link, second try", a["img_src"]))
    return out

def video_frame(src, at):
    """One still frame from a video file or link, `at` seconds in."""
    exe = media.ffmpeg_bin()
    if not exe:
        raise RuntimeError("no ffmpeg")
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "f.jpg")
        subprocess.run([exe, "-y", "-loglevel", "error", "-ss", str(at), "-i", src, "-frames:v", "1", "-q:v", "2", out],
                       capture_output=True, timeout=90)
        with Image.open(out) as im:
            return media.to_rgb(im)


def fetch(src):
    if isinstance(src, tuple) and src[0] == "frame":
        return video_frame(src[1], src[2])
    if isinstance(src, tuple):
        with Image.open(os.path.join(library.DOCS, src[1])) as im:
            return media.to_rgb(im)
    r = requests.get(src, headers=media.UA, timeout=20)
    r.raise_for_status()
    return media.to_rgb(Image.open(io.BytesIO(r.content)))

def repair(k, a, media_map, large, ph):
    """Tries the other pictures; saves the first good one as the ad's picture. Returns its label or ''."""
    rel = f"media/{a['p'][0]}/{a['id']}.jpg"
    for label, src in candidates(a):
        try:
            im = fetch(src)
        except Exception:
            continue
        if im.size[0] <= 120 or inspect(im) or bad_pic(im):
            continue  # YouTube's 120px "no picture" placeholder, or another broken picture
        media.write(rel, media.jpeg(im, media.THUMB))
        media_map[k] = rel
        if max(im.size) > media.THUMB[0] * 1.3:
            media.write(rel[:-4] + "_l.jpg", media.jpeg(im, media.LARGE))
            large[k] = rel[:-4] + "_l.jpg"
        else:
            large[k] = ""
        ph[k] = media.dhash(im)
        return label
    return ""

def run(max_fix=200):
    global VIS, VIDS
    try:
        VIS = __import__("vision").run() or {}  # is each saved picture really the ad? (checks new ads as they come in)
    except Exception as e:
        print(" content check skipped:", str(e)[:200])
    ads, _ = library.build_ads()
    for k, a in ads.items():
        a["key"] = k
    try:
        __import__("archive").attach(list(ads.values()))
    except Exception as e:
        print(" archive not attached:", str(e)[:100])
    media_map = library.load_json(library.MEDIA, {})
    failed = media_map.get("_failed", {})
    large = library.load_json(media.LARGES, {})
    ph = library.load_json(media.PHASH, {})
    vids = library.load_json(media.VIDEOS, {})
    VIDS = vids
    tags = library.load_json(library.TAGS, {})
    q = library.load_json(QUAL, {})
    today = date.today().isoformat()
    tried, newly, n = 0, [], Counter()
    for k, a in ads.items():
        rel = media_map.get(k) if isinstance(media_map.get(k), str) else ""
        rec = q.get(k) or {}
        prob, out = examine(k, a, rel, tags, rec, failed)
        if prob is None:
            continue
        if not prob:
            out["st"] = "fixed" if rec.get("st") == "fixed" else "ok"
            for x in ("why", "tries", "d") if out["st"] == "ok" else ():
                out.pop(x, None)
            q[k] = out
            n[out["st"]] += 1
            continue
        if rec.get("st") in ("text", "gone") and rec.get("tries", 0) >= MAX_TRIES:
            q[k] = out
            n[rec["st"]] += 1
            continue
        fixed = ""
        if tried < max_fix:
            tried += 1
            fixed = repair(k, a, media_map, large, ph)
        if fixed:
            p, w, h = check_file(media_map[k])
            out.update({"st": "fixed", "why": prob, "src": fixed, "d": out.get("d") or today, "p": p, "w": w, "h": h,
                        "f": sig(os.path.join(library.DOCS, media_map[k]))})
            out.pop("tries", None)
            if not has_copy(a):
                tags.pop(k, None)  # the AI read the broken picture; let it read the new one
            print(f" fixed {a['n']} {a['p']} {a['id']}: {prob} -> {fixed}")
        else:
            usable = has_copy(a) or bool(a.get("yt")) or k in vids
            out.update({"st": "text" if usable else "gone", "why": prob, "d": out.get("d") or today,
                        "tries": rec.get("tries", 0) + 1})
            if rec.get("st") != out["st"]:
                newly.append((a, out["st"], prob))
        q[k] = out
        n[out["st"]] += 1
    library.save_json(QUAL, q)
    library.save_json(library.MEDIA, media_map)
    library.save_json(media.LARGES, large)
    library.save_json(media.PHASH, ph)
    library.save_json(library.TAGS, tags)
    line = (f"Ad health: {n['ok']} fine, {n['fixed']} repaired, {n['text']} shown as copy only (picture broken), "
            f"{n['gone']} set aside as unavailable")
    print(line)
    for a, st, prob in newly:
        print(f"::warning::{a['n']} {a['p']} ad {a['id']} {'set aside' if st == 'gone' else 'picture dropped'}: {REASON[prob]}")
    sm = os.environ.get("GITHUB_STEP_SUMMARY")
    if sm:
        with open(sm, "a") as f:
            f.write(f"\n### Ad health\n{line}\n")
            for a, st, prob in newly[:40]:
                f.write(f"- {a['n']} · {a['p']} · {a['id']}: {REASON[prob]} ({'unavailable' if st == 'gone' else 'copy only'})\n")
    return n

def apply(out):
    """Called by library.build: adds the health status and picture shape to each ad for the site."""
    q = library.load_json(QUAL, {})
    n = Counter()
    vis = library.load_json(os.path.join(library.DATA, "vision.json"), {}).get("ads") or {}
    for a in out:
        r = q.get(a["key"])
        if not r:
            continue
        if r.get("w") and r.get("h") and r.get("p") == "":
            a["ar"] = round(r["w"] / r["h"], 3)
        st = r.get("st")
        if st in ("fixed", "text", "gone"):
            a["q"] = {"st": st, "why": r.get("why", ""), "src": r.get("src", ""), "d": r.get("d", ""),
                      "msg": REASON.get(r.get("why", ""), "") + (" (spotted by: " + vis[a["key"]]["how"] + ")" if (vis.get(a["key"]) or {}).get("how") and st != "fixed" else "")}
            n[st] += 1
        if st in ("text", "gone"):
            a["img"] = ""
            a.pop("img_l", None)
            a.pop("ar", None)
            a.pop("seen_text", None)
        if st == "gone":
            a["gone"] = 1
            a.pop("ws", None)
            a.pop("stand", None)
            a.pop("offer", None)
            a["camp"] = ["Unknown"]
    return dict(n)

if __name__ == "__main__":
    run()
