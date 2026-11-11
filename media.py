"""Saves media for every ad, so the site and emails keep working after Facebook's links expire (about 5 days)
and after ads stop running:

docs/media/m/<ad id>.jpg      small copy for the grid (420px, ~25 KB); Meta in m/, Google in g/
docs/media/m/<ad id>_l.jpg    larger copy for the zoom viewer (960px, ~90 KB), only if the original is bigger
docs/media/v/<ad id>.mp4      Meta videos, shrunk to 640px on the long side at a low bitrate (~1 MB per 30s)
data/media.json               {ad key: small copy} plus retry counts for failing links
data/media_large.json         {ad key: large copy, or "" when the small copy is already full size}
data/videos.json              {ad key: video} plus retry counts
data/phash.json               {ad key: 64-bit picture fingerprint}, used by the winner score to spot reused creative

Google/YouTube videos aren't downloaded (YouTube's terms); the site plays them in YouTube's embedded player.
Run: python media.py
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
import time

import requests
from PIL import Image

import library

THUMB = (420, 640, 74)   # max width, max height, JPEG quality
LARGE = (960, 1200, 72)
VIDEO_BOX, VIDEO_CRF, VIDEO_MAXRATE, AUDIO_RATE, VIDEO_MAX_S = 640, 30, "450k", "48k", 120
VIDEO_MINUTES = 30  # time budget per run; the rest wait for the next run
LARGES = os.path.join(library.DATA, "media_large.json")
VIDEOS = os.path.join(library.DATA, "videos.json")
PHASH = os.path.join(library.DATA, "phash.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def to_rgb(im):
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def jpeg(im, box):
    w, h, q = box
    im = im.copy()
    im.thumbnail((w, h), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=q, optimize=True, progressive=True)
    return out.getvalue()


def shrink(data):
    """Small JPEG bytes and size (kept for older callers)."""
    small = jpeg(to_rgb(Image.open(io.BytesIO(data))), THUMB)
    return small, Image.open(io.BytesIO(small)).size


def dhash(im):
    """64-bit difference hash: near-identical pictures get near-identical hashes, even resized or recompressed."""
    g = im.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    return f"{bits:016x}"


def write(rel, data):
    path = os.path.join(library.DOCS, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def save_images(ads, max_new):
    media = library.load_json(library.MEDIA, {})
    fails = media.setdefault("_failed", {})
    large = library.load_json(LARGES, {})
    ph = library.load_json(PHASH, {})
    todo = [(k, a) for k, a in ads.items()
            if a.get("img_src") and (k not in media or k not in large) and fails.get(k, 0) < 3]
    todo.sort(key=lambda x: x[0] in media)  # ads with no picture at all first
    print(f"Images: {len(todo)} ads need a picture or a larger copy")
    saved = big = 0
    for i, (k, a) in enumerate(todo[:max_new]):
        base = f"media/{a['p'][0]}/{a['id']}"
        try:
            r = requests.get(a["img_src"], headers=UA, timeout=30)
            r.raise_for_status()
            im = to_rgb(Image.open(io.BytesIO(r.content)))
            if k not in media:
                write(base + ".jpg", jpeg(im, THUMB))
                media[k] = base + ".jpg"
                saved += 1
            if max(im.size) > THUMB[0] * 1.3:
                write(base + "_l.jpg", jpeg(im, LARGE))
                large[k] = base + "_l.jpg"
                big += 1
            else:
                large[k] = ""
            ph[k] = dhash(im)
            fails.pop(k, None)
        except Exception as e:
            fails[k] = fails.get(k, 0) + 1
            if fails[k] == 1:
                print(f"  {a['n']} {a['p']} {a['id']}: {str(e)[:100]}")
        if i and i % 100 == 0:
            library.save_json(library.MEDIA, media)
            library.save_json(LARGES, large)
            library.save_json(PHASH, ph)
        time.sleep(0.05)
    # fingerprints for pictures saved earlier whose links no longer work
    for k, rel in list(media.items()):
        if k.startswith("_") or k in ph or not isinstance(rel, str):
            continue
        try:
            with Image.open(os.path.join(library.DOCS, rel)) as im:
                ph[k] = dhash(to_rgb(im))
        except Exception:
            pass
    library.save_json(library.MEDIA, media)
    library.save_json(LARGES, large)
    library.save_json(PHASH, ph)
    print(f"Images: saved {saved} new, {big} larger copies, {len(fails)} links failing")
    return saved


def ffmpeg_bin():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        print("  no ffmpeg available, videos skipped:", str(e)[:100])
        return None


def link_expiry(url):
    """Facebook media links carry their expiry time as hex in oe=."""
    m = re.search(r"[?&]oe=([0-9A-Fa-f]{6,10})", url or "")
    return int(m.group(1), 16) if m else None


def save_videos(ads, max_new=400):
    vids = library.load_json(VIDEOS, {})
    fails = vids.setdefault("_failed", {})
    now = time.time()
    todo = []
    for k, a in ads.items():
        if a["p"] != "meta" or not a.get("video_src") or k in vids or fails.get(k, 0) >= 3:
            continue
        exp = link_expiry(a["video_src"])
        if exp and exp < now:
            fails[k] = 3  # link already expired; the poster frame stays
            continue
        todo.append((exp or now + 5 * 86400, k, a))
    todo.sort(key=lambda x: x[0])  # links that expire soonest first
    print(f"Videos: {len(todo)} Meta videos to save")
    exe = ffmpeg_bin() if todo else None
    if not exe:
        library.save_json(VIDEOS, vids)
        return 0
    saved, total, started = 0, 0, time.time()
    for _, k, a in todo[:max_new]:
        if time.time() - started > VIDEO_MINUTES * 60:
            print("  time budget used up; the rest are saved next run")
            break
        try:
            with tempfile.TemporaryDirectory() as td:
                src, dst = os.path.join(td, "in"), os.path.join(td, "out.mp4")
                with requests.get(a["video_src"], headers=UA, timeout=60, stream=True) as r:
                    r.raise_for_status()
                    with open(src, "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk)
                box = f"scale='min({VIDEO_BOX},iw)':'min({VIDEO_BOX},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
                cmd = [exe, "-y", "-loglevel", "error", "-i", src, "-t", str(VIDEO_MAX_S), "-vf", box,
                       "-c:v", "libx264", "-preset", "medium", "-crf", str(VIDEO_CRF),
                       "-maxrate", VIDEO_MAXRATE, "-bufsize", "900k", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-b:a", AUDIO_RATE, "-ac", "1", "-movflags", "+faststart", dst]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if p.returncode != 0 or not os.path.exists(dst):
                    raise RuntimeError("ffmpeg: " + (p.stderr or "")[-200:])
                with open(dst, "rb") as f:
                    data = f.read()
            rel = f"media/v/{a['id']}.mp4"
            write(rel, data)
            vids[k] = rel
            fails.pop(k, None)
            saved += 1
            total += len(data)
        except Exception as e:
            fails[k] = fails.get(k, 0) + 1
            if fails[k] == 1:
                print(f"  {a['n']} {a['id']}: {str(e)[:200]}")
        if saved and saved % 20 == 0:
            library.save_json(VIDEOS, vids)
    library.save_json(VIDEOS, vids)
    print(f"Videos: saved {saved} ({total / 1e6:.1f} MB), {len(fails)} failing or expired")
    return saved


def run(max_new=3000):
    ads, _ = library.build_ads()
    saved = save_images(ads, max_new)
    save_videos(ads)
    return saved


if __name__ == "__main__":
    run()
