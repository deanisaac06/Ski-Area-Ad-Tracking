"""Saves a small copy of every ad's image (or video poster) into docs/media/, so the site and emails keep
working after Facebook's links expire (about 5 days) and after ads stop running.

  docs/media/m/<ad id>.jpg   Meta ads
  docs/media/g/<ad id>.jpg   Google ads
  data/media.json            {ad key: "media/m/<id>.jpg"} plus a retry count for links that failed

Run:  python media.py
"""
import io
import os
import time

import requests
from PIL import Image

import library

MAX_W, MAX_H, QUALITY = 420, 640, 74
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def shrink(data):
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return out.getvalue(), im.size


def run(max_new=3000):
    ads, _ = library.build_ads()
    media = library.load_json(library.MEDIA, {})
    fails = media.setdefault("_failed", {})
    todo = [(k, a) for k, a in ads.items() if k not in media and a.get("img_src") and fails.get(k, 0) < 3]
    print(f"Media: {len(todo)} ads need an image saved")
    saved = 0
    for k, a in todo[:max_new]:
        rel = f"media/{a['p'][0]}/{a['id']}.jpg"
        try:
            r = requests.get(a["img_src"], headers=UA, timeout=30)
            r.raise_for_status()
            data, size = shrink(r.content)
            path = os.path.join(library.DOCS, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            media[k] = rel
            fails.pop(k, None)
            saved += 1
        except Exception as e:
            fails[k] = fails.get(k, 0) + 1
            if fails[k] == 1:
                print(f"  {a['n']} {a['p']} {a['id']}: {str(e)[:100]}")
        if saved and saved % 100 == 0:
            library.save_json(library.MEDIA, media)
        time.sleep(0.05)
    library.save_json(library.MEDIA, media)
    print(f"Media: saved {saved}, {len(fails)} links failing")
    return saved


if __name__ == "__main__":
    run()
