"""Keeps a lasting record of every ad, so it can still be studied after the resort takes it down.

Each run, after media.py has saved the main picture and any Meta video:
  frames   Google video ads: YouTube's own still frames of the video, saved as small pictures, so there's
           something to look at even if the resort later deletes or hides the YouTube video
  notes    Google (YouTube) videos and saved Meta videos: Gemini watches each video once and writes down the
           voiceover, on-screen text, offer and scenes. Plain text, searchable, and it outlives the video
  cards    every card of a Meta carousel / dynamic ad and every Google variation, not just the first
  landing  a screenshot and the text of each ad's landing page around when the ad was first seen
           (taken again for a later ad if the newest snapshot is older than that ad)
  health   counts for the site and the run log, including Meta videos whose links expired before they were saved

data/archive.json  {ad key: {"frames": [...], "cards": [...], "note": {...}, "lp": {...}}} plus "_failed", "_health"
data/landing.json  {page key: [{"d": date, "img": path, "txt": path, "u": url, "t": title}, ...]}
docs/media/y/ YouTube frames, docs/media/c/ cards, docs/media/lp/ landing screenshots (.jpg) and text (.txt)
Run: python archive.py
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from urllib.parse import urlsplit

import requests
from PIL import Image

import library
import media

ARCH = os.path.join(library.DATA, "archive.json")
LANDING = os.path.join(library.DATA, "landing.json")
CARD = (640, 800, 72)  # max width, max height, JPEG quality
FRAME = (480, 360, 70)
LP_W, LP_MAX_H = 1280, 2400  # browser width, longest part of a page kept (px, before shrinking)
LP_IMG = (720, 1350, 64)
LP_TEXT = 4000  # characters of page text kept
YT_FRAMES = ["maxresdefault", "hq1", "hq2", "hq3"]  # cover, then frames at about 25%, 50%, 75%
NOTE_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash-lite"]  # lite first: bigger free quota
SKIP_HOSTS = ("facebook.com", "fb.com", "fb.me", "instagram.com", "apps.apple.com", "play.google.com",
              "messenger.com", "wa.me", "whatsapp.com")
YT = re.compile(r"(?:ytimg\.com/vi(?:_webp)?/|youtube(?:-nocookie)?\.com/(?:watch\?(?:[^\"\s]*?&)?v=|embed/|shorts/|v/)"
                r"|youtu\.be/|\"(?:videoId|youtubeVideoId|youtube_video_id|ytVideoId)\"\s*:\s*\")([\w-]{11})")

NOTE_PROMPT = """You are archiving a video ad from {resort} (a ski resort) so it can still be studied after it's taken down.
Watch it and write down what's in it. Return JSON only, with these fields:
"summary": 1-2 sentences: what happens and what it's selling
"hook": what happens in the first 3 seconds, under 15 words
"voiceover": the spoken words (word for word if under about 80 words, otherwise a close summary); "" if none
"onscreen": the text shown on screen, in order, separated by " / "; "" if none
"offer": the concrete offer or call to action, under 15 words; "" if none
"scenes": 4-10 short scene descriptions in order, each starting with a rough time like "0:03"
"music": music and mood, under 8 words
"length": length in seconds (a number)"""


# ------------------------------------------------------------------ helpers used by library.py
def yt_id(item):
    """YouTube ID of a Google video ad, found anywhere in the raw download (usually its preview picture)."""
    m = YT.search(json.dumps(item))
    return m.group(1) if m else ""


def meta_cards(snapshot, cards):
    urls = []
    for c in cards:
        u = c.get("original_image_url") or c.get("resized_image_url") or c.get("video_preview_image_url")
        if u:
            urls.append(u)
    for im in (snapshot.get("images") or [])[1:] + (snapshot.get("extra_images") or []):
        if isinstance(im, dict):
            u = im.get("original_image_url") or im.get("resized_image_url")
            if u:
                urls.append(u)
    return list(dict.fromkeys(urls))[:12]


def google_cards(variations):
    return list(dict.fromkeys(v["imageUrl"] for v in variations if v.get("imageUrl")))[:12]


def attach(ads):
    """Adds each ad's archive (frames, cards, note, landing snapshot) for the site."""
    arc = library.load_json(ARCH, {})
    for a in ads:
        e = {k: v for k, v in (arc.get(a["key"]) or {}).items() if v}
        if e:
            a["arc"] = e


# ------------------------------------------------------------------ pictures
def grab(url, timeout=30):
    r = requests.get(url, headers=media.UA, timeout=timeout)
    r.raise_for_status()
    return media.to_rgb(Image.open(io.BytesIO(r.content)))


def ham(x, y):
    return bin(int(x, 16) ^ int(y, 16)).count("1")


def save_frames(ads, arc, fails, until):
    todo = [(k, a) for k, a in ads.items()
            if a.get("yt") and "frames" not in arc.get(k, {}) and fails.get("f" + k, 0) < 3]
    todo.sort(key=lambda x: x[1].get("start") or "", reverse=True)
    done = {}  # several Google creatives can share one YouTube video
    n = 0
    for k, a in todo:
        if time.time() > until:
            break
        got = done.get(a["yt"])
        if got is None:
            got = []
            for i, name in enumerate(YT_FRAMES):
                try:
                    im = grab(f"https://i.ytimg.com/vi/{a['yt']}/{name}.jpg", 20)
                    if im.size[0] <= 120:
                        continue  # YouTube's grey "no picture" placeholder
                    rel = f"media/y/{a['yt']}_{i}.jpg"
                    media.write(rel, media.jpeg(im, CARD if i == 0 else FRAME))
                    got.append(rel)
                except Exception:
                    pass
            done[a["yt"]] = got
        if got:
            arc.setdefault(k, {})["frames"] = got
            fails.pop("f" + k, None)
            n += 1
        else:
            fails["f" + k] = fails.get("f" + k, 0) + 1
    print(f"Archive: YouTube frames saved for {n} of {len(todo)} video ads")


def save_cards(ads, arc, fails, ph, until):
    todo = [(k, a) for k, a in ads.items()
            if a.get("cards_src") and "cards" not in arc.get(k, {}) and fails.get("c" + k, 0) < 3]
    todo.sort(key=lambda x: x[1].get("start") or "", reverse=True)
    todo.sort(key=lambda x: x[1]["p"] != "meta")  # Meta first: its links expire in about 5 days
    n = extra = 0
    for k, a in todo:
        if time.time() > until:
            break
        main = a.get("img_src") or ""
        seen = [ph[k]] if ph.get(k) else []
        got, bad, tried = [], 0, 0
        for i, u in enumerate(a["cards_src"]):
            if u == main:
                continue
            tried += 1
            try:
                im = grab(u, 12)
            except Exception:
                bad += 1
                continue
            h = media.dhash(im)
            if any(ham(h, x) <= 4 for x in seen):
                continue  # same picture as the main one or an earlier card
            seen.append(h)
            rel = f"media/c/{a['p'][0]}{a['id']}_{i}.jpg"
            media.write(rel, media.jpeg(im, CARD))
            got.append(rel)
        if tried and bad == tried:
            fails["c" + k] = fails.get("c" + k, 0) + 1
            continue
        arc.setdefault(k, {})["cards"] = got  # [] = checked, nothing beyond the main picture
        fails.pop("c" + k, None)
        n += 1
        extra += len(got)
    print(f"Archive: checked {n} of {len(todo)} ads for extra cards/versions, saved {extra}")


# ------------------------------------------------------------------ AI video notes
def parse_note(text):
    try:
        t = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        try:
            d = json.loads(t)
        except ValueError:
            m = re.search(r"\{.*\}", t, re.S)
            d = json.loads(m.group(0)) if m else {}
        if isinstance(d, list):
            d = d[0] if d else {}
        out = {}
        for f, n in (("summary", 400), ("hook", 160), ("voiceover", 1500), ("onscreen", 600), ("offer", 160), ("music", 80)):
            if d.get(f):
                out[f] = str(d[f])[:n]
        if isinstance(d.get("scenes"), list):
            out["scenes"] = [str(x)[:140] for x in d["scenes"]][:12]
        try:
            out["len"] = round(float(d.get("length")))
        except (TypeError, ValueError):
            pass
        return out
    except Exception:
        return {}


def save_notes(ads, arc, fails, until, max_calls=30):
    import ai
    if not ai.key():
        print("Archive: video notes skipped (no GEMINI_API_KEY)")
        return
    vids = library.load_json(media.VIDEOS, {})
    by_yt = {ads[k]["yt"]: e["note"] for k, e in arc.items()
             if not k.startswith("_") and e.get("note") and ads.get(k, {}).get("yt")}
    todo = []
    for k, a in ads.items():
        if arc.get(k, {}).get("note") or fails.get("n" + k, 0) >= 2:
            continue
        if a.get("yt"):
            if a["yt"] in by_yt:
                arc.setdefault(k, {})["note"] = by_yt[a["yt"]]
                continue
            todo.append((a.get("start") or "", k, a, "yt"))
        elif a["p"] == "meta" and isinstance(vids.get(k), str):
            todo.append((a.get("start") or "", k, a, "mp4"))
    todo.sort(key=lambda x: (x[0], x[1]), reverse=True)
    print(f"Archive: {len(todo)} videos to describe")
    calls = misses = done = 0
    for _, k, a, kind in todo:
        if calls >= max_calls or misses >= 3 or time.time() > until - 30:
            break
        if kind == "yt" and a["yt"] in by_yt:
            arc.setdefault(k, {})["note"] = by_yt[a["yt"]]
            continue
        prompt = NOTE_PROMPT.format(resort=a["n"])
        if kind == "yt":
            parts = [{"file_data": {"file_uri": f"https://www.youtube.com/watch?v={a['yt']}"}}, {"text": prompt}]
        else:
            path = os.path.join(library.DOCS, vids[k])
            if not os.path.exists(path) or os.path.getsize(path) > 15e6:
                continue
            with open(path, "rb") as f:
                parts = [{"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(f.read()).decode()}},
                         {"text": prompt}]
        calls += 1
        try:
            out = ai.ask(parts, min(until, time.time() + 150), models=NOTE_MODELS, json_out=True)
        except Exception as e:
            print(f"  {a['n']} {a['id']}: {str(e)[:120]}")
            out = None
        note = parse_note(out) if out else {}
        if note.get("summary") or note.get("voiceover") or note.get("onscreen"):
            note["src"] = "YouTube video" if kind == "yt" else "saved video"
            note["d"] = date.today().isoformat()
            arc.setdefault(k, {})["note"] = note
            if kind == "yt":
                by_yt[a["yt"]] = note
            fails.pop("n" + k, None)
            done += 1
            misses = 0
        else:
            fails["n" + k] = fails.get("n" + k, 0) + 1
            misses += 1
        time.sleep(ai.PACE)
    print(f"Archive: described {done} videos in {calls} AI calls")


# ------------------------------------------------------------------ landing pages
def page_key(url):
    p = urlsplit(url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + (p.path.rstrip("/") or "/") if host else ""


def shift(d, n):
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def pick(snaps, fs):
    """The first snapshot taken from 3 days before the ad was first seen; else the closest one."""
    later = [s for s in snaps if s["d"] >= shift(fs, -3)]
    if later:
        return min(later, key=lambda s: s["d"])
    return min(snaps, key=lambda s: abs((date.fromisoformat(s["d"]) - date.fromisoformat(fs)).days))


def launch(pw):
    try:
        return pw.chromium.launch()
    except Exception:
        print("  installing the headless browser for landing-page snapshots...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                       capture_output=True, timeout=900)
        return pw.chromium.launch()


def snap(page, url, pk, today):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")  # closes many sign-up pop-ups
    except Exception:
        pass
    page.wait_for_timeout(1200)
    try:
        h = int(page.evaluate("document.documentElement.scrollHeight") or 900)
    except Exception:
        h = 900
    png = page.screenshot(full_page=True, clip={"x": 0, "y": 0, "width": LP_W, "height": max(600, min(LP_MAX_H, h))},
                          timeout=30000)
    title = (page.title() or "")[:160]
    try:
        text = page.inner_text("body", timeout=5000)
    except Exception:
        text = ""
    text = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\r\f\v]+", " ", text)).strip()[:LP_TEXT]
    base = f"media/lp/{hashlib.sha1(pk.encode()).hexdigest()[:10]}_{today.replace('-', '')}"
    media.write(base + ".jpg", media.jpeg(media.to_rgb(Image.open(io.BytesIO(png))), LP_IMG))
    media.write(base + ".txt", text.encode("utf-8"))
    return {"d": today, "img": base + ".jpg", "txt": base + ".txt", "u": page.url[:300], "t": title}


def save_landing(ads, arc, fails, until, max_new=40):
    pages = library.load_json(LANDING, {})
    today = date.today().isoformat()
    keyed = {}
    for k, a in ads.items():
        u = (a.get("link") or "").strip()
        if not u or " " in u:
            continue
        if not u.startswith("http"):
            u = "https://" + u
        pk = page_key(u)
        if not pk or any(h in pk.split("/")[0] for h in SKIP_HOSTS):
            continue
        keyed[k] = (pk, u)
    need = {}
    for k, (pk, u) in keyed.items():
        a = ads[k]
        fs = a.get("first_seen") or today
        if a.get("live") and fails.get("l" + pk, 0) < 3 and not any(s["d"] >= shift(fs, -3) for s in pages.get(pk, [])):
            need.setdefault(pk, u)
    print(f"Archive: {len(need)} landing pages to snapshot")
    done = 0
    if need and time.time() < until - 90:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  playwright isn't installed - landing pages skipped")
            need = {}
        if need:
            with sync_playwright() as pw:
                br = launch(pw)
                ctx = br.new_context(viewport={"width": LP_W, "height": 900}, user_agent=media.UA["User-Agent"],
                                     locale="en-US")
                for pk, u in list(need.items())[:max_new]:
                    if time.time() > until:
                        break
                    page = ctx.new_page()
                    try:
                        pages.setdefault(pk, []).append(snap(page, u, pk, today))
                        fails.pop("l" + pk, None)
                        done += 1
                    except Exception as e:
                        fails["l" + pk] = fails.get("l" + pk, 0) + 1
                        print(f"  {u[:80]}: {str(e)[:120]}")
                    finally:
                        page.close()
                    library.save_json(LANDING, pages)
                br.close()
    for k, (pk, u) in keyed.items():
        if pages.get(pk):
            arc.setdefault(k, {})["lp"] = pick(pages[pk], ads[k].get("first_seen") or today)
    print(f"Archive: {done} landing pages saved this run")


# ------------------------------------------------------------------ health
def health():
    vids = library.load_json(media.VIDEOS, {})
    arc = library.load_json(ARCH, {})
    ent = [e for k, e in arc.items() if not k.startswith("_")]
    return {"videos": sum(1 for k, v in vids.items() if not k.startswith("_") and v),
            "videos_missed": sum(1 for n in (vids.get("_failed") or {}).values() if n >= 3),
            "frames": sum(1 for e in ent if e.get("frames")),
            "notes": sum(1 for e in ent if e.get("note")),
            "cards": sum(len(e.get("cards") or []) for e in ent),
            "pages": sum(len(v) for v in library.load_json(LANDING, {}).values())}


def report_health(ads):
    h = health()
    vids = library.load_json(media.VIDEOS, {})
    f = vids.get("_failed") or {}
    pending = [k for k, a in ads.items() if a["p"] == "meta" and a.get("video_src") and k not in vids and f.get(k, 0) < 3]
    soon = sum(1 for k in pending if (media.link_expiry(ads[k]["video_src"]) or 9e12) - time.time() < 36 * 3600)
    line = (f"Archive health: {h['videos']} Meta videos saved, {h['videos_missed']} missed (link expired or failed), "
            f"{len(pending)} waiting ({soon} expire within 36h); {h['frames']} YouTube ads with frames, "
            f"{h['notes']} videos described, {h['cards']} extra cards/versions, {h['pages']} landing-page snapshots")
    print(line)
    arc = library.load_json(ARCH, {})
    before = (arc.get("_health") or {}).get("videos_missed", h["videos_missed"])
    if h["videos_missed"] > before:
        print(f"::warning::{h['videos_missed'] - before} Meta videos expired or failed before they could be saved")
    if soon:
        print(f"::warning::{soon} Meta videos expire within 36 hours and aren't saved yet")
    arc["_health"] = h
    library.save_json(ARCH, arc)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(line + "\n")


def run(max_seconds=900):
    t0 = time.time()
    ads, _ = library.build_ads()
    for k, a in ads.items():
        a["key"] = k
    arc = library.load_json(ARCH, {})
    fails = arc.setdefault("_failed", {})
    ph = library.load_json(media.PHASH, {})
    steps = (("frames", lambda u: save_frames(ads, arc, fails, u), 0.1),
             ("cards", lambda u: save_cards(ads, arc, fails, ph, u), 0.3),
             ("notes", lambda u: save_notes(ads, arc, fails, u), 0.6),
             ("landing", lambda u: save_landing(ads, arc, fails, u), 1.0))
    for name, fn, share in steps:
        try:
            fn(t0 + max_seconds * share)
        except Exception as e:
            print(f"Archive: {name} step failed: {str(e)[:200]}")
        library.save_json(ARCH, arc)
    try:
        report_health(ads)
    except Exception as e:
        print("Archive: health check failed:", str(e)[:200])


if __name__ == "__main__":
    run()
