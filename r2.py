"""Moves saved media off GitHub to Cloudflare R2, so the site stays well under GitHub Pages' 1 GB limit.

Videos (docs/media/v/) and pictures (docs/media/m, g, c, y, lp - ad images, large copies, YouTube frames, cards and
landing-page screenshots) are saved to docs/media/ first, as before: the AI tags, the content check and the health
check read them there in the same run. At the end of every run this uploads every file still in those folders to
the R2 bucket, checks that the public copy is there and the same size, and only then deletes the GitHub copy.
Landing-page text (.txt) stays on GitHub (small, and passes.py reads it).

data/media.json and friends keep the same "media/..." paths. url() turns a path into its R2 address once it's
uploaded (library.py does this for the site), and local() gives the steps that need the file itself a copy:
the GitHub file while it's still there, else a download of the R2 copy (cached for the run).

Keys in the bucket: videos at the top level (<id>.mp4, as before), pictures under their folder (m/<id>.jpg).

One-time setup (by you, in Cloudflare):
  1. Cloudflare dashboard > R2 Object Storage: turn R2 on (free up to 10 GB stored; Cloudflare asks for a card
     but doesn't charge under the free limits).
  2. My Profile > API Tokens > Create token with "Workers R2 Storage: Edit" on this account, saved as the
     CLOUDFLARE_R2_TOKEN repository secret. CLOUDFLARE_ACCOUNT_ID is already set.
  3. Optional but recommended for pictures: connect a custom domain to the bucket (R2 > bucket > Settings >
     Custom Domains) and save it as the R2_PUBLIC_URL repository variable. The free r2.dev address is rate
     limited by Cloudflare, which a grid of hundreds of thumbnails can hit.
This script makes the bucket (R2_BUCKET, default ski-ad-videos) and turns on its public r2.dev address itself.
Until that's done, files simply stay on GitHub and the run log says why. Nothing is deleted unless the R2 copy
checked out.

data/r2.json {"base": public address, "bucket": name, "up": {path: bytes}, "_failed": {path: tries}}
Run: python r2.py            (move what's waiting)
     python r2.py --status   (how much is where)
"""
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import library

STATE = os.path.join(library.DATA, "r2.json")
API = "https://api.cloudflare.com/client/v4"
BUCKET = os.environ.get("R2_BUCKET") or "ski-ad-videos"
MAX_MINUTES = int(os.environ.get("R2_MAX_MINUTES") or 25)
PIC_DIRS = ("m", "g", "c", "y", "lp")      # picture folders under docs/media/
PIC_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
WORKERS = 6
RATE = float(os.environ.get("R2_PUTS_PER_SECOND") or 3.5)  # Cloudflare's API limit is 1,200 calls per 5 minutes (4/s)
CACHE = os.path.join(tempfile.gettempdir(), "r2-cache")
_state = {}


def state():
    if not _state:
        _state.update(library.load_json(STATE, {}))
    return _state


def key(rel):
    """Object name in the bucket: videos sit at the top (as they always have), pictures under their folder."""
    rel = rel.replace("\\", "/")
    return rel.split("/")[-1] if rel.startswith("media/v/") else rel[len("media/"):] if rel.startswith("media/") else rel


def on_r2(rel):
    return bool(rel) and rel in (state().get("up") or {}) and bool(state().get("base"))


def url(rel):
    """The address the site should use for a saved file: R2 once it's uploaded, else the GitHub copy."""
    s = state()
    if on_r2(rel) and not os.path.exists(os.path.join(library.DOCS, rel)):
        return s["base"].rstrip("/") + "/" + key(rel)
    return rel or ""


def size(rel):
    """Bytes of a saved file, wherever it is ('' path or unknown: 0)."""
    p = os.path.join(library.DOCS, rel or "")
    if rel and os.path.isfile(p):
        return os.path.getsize(p)
    return int((state().get("up") or {}).get(rel) or 0)


def exists(rel):
    return bool(rel) and (os.path.isfile(os.path.join(library.DOCS, rel)) or on_r2(rel))


def local(rel):
    """A path to read a saved file from: the GitHub copy if it's still here, else a cached download of the R2 copy;
    '' if there is neither. For steps that need the file itself (AI tags, OCR, health and content checks, email)."""
    if not rel:
        return ""
    p = os.path.join(library.DOCS, rel)
    if os.path.isfile(p):
        return p
    if not on_r2(rel):
        return ""
    c = os.path.join(CACHE, rel)
    if os.path.isfile(c):
        return c
    try:
        r = requests.get(state()["base"].rstrip("/") + "/" + key(rel), timeout=60)
        r.raise_for_status()
        os.makedirs(os.path.dirname(c), exist_ok=True)
        with open(c, "wb") as f:
            f.write(r.content)
        return c
    except Exception as e:
        print(" R2 copy not fetched:", rel, str(e)[:100])
        return ""


def fetch(rel):
    """A temporary local copy of a video that's on R2, for steps that need the file itself; '' if not possible."""
    u = url(rel)
    if not u.startswith("http"):
        return ""
    try:
        r = requests.get(u, timeout=120)
        r.raise_for_status()
        fd, path = tempfile.mkstemp(suffix=".mp4")
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        return path
    except Exception as e:
        print(" R2 copy not fetched:", str(e)[:120])
        return ""


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _ok(r):
    try:
        j = r.json()
    except ValueError:
        j = {}
    if not isinstance(j, dict):
        j = {}
    if r.status_code >= 300 or j.get("success") is False:
        msg = "; ".join(str(e.get("message")) for e in (j.get("errors") or []) if isinstance(e, dict)) or r.text[:200]
        raise RuntimeError(f"{r.status_code} {msg}")
    return j.get("result")


def setup(acct, token):
    """Makes sure the bucket exists and has a public address; returns that address."""
    s = state()
    base = os.environ.get("R2_PUBLIC_URL") or s.get("base")
    if base and s.get("bucket") == BUCKET:
        return base
    b = f"{API}/accounts/{acct}/r2/buckets"
    r = requests.get(f"{b}/{BUCKET}", headers=_h(token), timeout=30)
    if r.status_code == 404:
        _ok(requests.post(b, headers=_h(token), json={"name": BUCKET}, timeout=30))
        print(f" R2: created bucket {BUCKET}")
    else:
        _ok(r)
    if not base:
        res = _ok(requests.put(f"{b}/{BUCKET}/domains/managed", headers=_h(token), json={"enabled": True}, timeout=30)) or {}
        dom = res.get("domain") if isinstance(res, dict) else ""
        if not dom:
            res = _ok(requests.get(f"{b}/{BUCKET}/domains/managed", headers=_h(token), timeout=30)) or {}
            dom = res.get("domain") if isinstance(res, dict) else ""
        if not dom:
            raise RuntimeError("Cloudflare didn't return a public r2.dev address for the bucket")
        base = "https://" + dom
    s["base"], s["bucket"] = base, BUCKET
    library.save_json(STATE, s, indent=1)
    print(f" R2: media is served from {base}")
    return base


def waiting():
    """[(rel, local path, bytes)] still on GitHub: videos first (biggest files), then pictures, biggest first."""
    out = []
    vdir = os.path.join(library.DOCS, "media", "v")
    if os.path.isdir(vdir):
        out += [("media/v/" + f, os.path.join(vdir, f)) for f in os.listdir(vdir) if f.endswith(".mp4")]
    pics = []
    for d in PIC_DIRS:
        pdir = os.path.join(library.DOCS, "media", d)
        if os.path.isdir(pdir):
            pics += [(f"media/{d}/{f}", os.path.join(pdir, f)) for f in os.listdir(pdir)
                     if os.path.splitext(f)[1].lower() in PIC_TYPES]
    out = [(r, p, os.path.getsize(p)) for r, p in out]
    pics = [(r, p, os.path.getsize(p)) for r, p in pics]
    return out + sorted(pics, key=lambda x: -x[2])


def run():
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_R2_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
    todo = waiting()
    if not todo:
        print("R2: nothing waiting to move off GitHub")
        return 0
    if not (acct and token):
        print(f"R2: {len(todo)} files stay on GitHub - CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_R2_TOKEN not set")
        return 0
    try:
        base = setup(acct, token)
    except Exception as e:
        print(f"::warning::R2 isn't ready, so {len(todo)} files stay on GitHub for now: {str(e)[:200]}")
        return 0
    s = state()
    up, fails = s.setdefault("up", {}), s.setdefault("_failed", {})
    lock, t0, done = threading.Lock(), time.time(), {"n": 0, "bytes": 0, "slow": 0}
    stop, pace, nxt = threading.Event(), threading.Lock(), [0.0]

    def throttle():
        with pace:
            wait = nxt[0] - time.time()
            nxt[0] = max(nxt[0], time.time()) + 1 / RATE
        if wait > 0:
            time.sleep(wait)

    def move(item):
        rel, path, n = item
        if stop.is_set() or fails.get(rel, 0) >= 5:
            return
        if time.time() - t0 > MAX_MINUTES * 60:
            stop.set()
            return
        ext = os.path.splitext(rel)[1].lower()
        ctype = "video/mp4" if ext == ".mp4" else PIC_TYPES.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as f:
                data = f.read()
            for attempt in range(4):  # Cloudflare's API allows ~1,200 calls per 5 minutes: back off on 429
                throttle()
                r = requests.put(f"{API}/accounts/{acct}/r2/buckets/{BUCKET}/objects/{key(rel)}",
                                 headers={**_h(token), "Content-Type": ctype}, data=data, timeout=180)
                if r.status_code != 429:
                    break
                with lock:
                    done["slow"] += 1
                time.sleep(15 * (attempt + 1))
            _ok(r)
            chk = requests.head(base.rstrip("/") + "/" + key(rel), timeout=60)
            if chk.status_code != 200 or int(chk.headers.get("content-length") or -1) != len(data):
                raise RuntimeError(f"public copy check failed (HTTP {chk.status_code})")
            with lock:
                up[rel] = len(data)
                fails.pop(rel, None)
                done["n"] += 1
                done["bytes"] += len(data)
                if done["n"] % 200 == 0:
                    library.save_json(STATE, s, indent=1)
            os.remove(path)  # the GitHub copy; the site now uses the R2 one
        except Exception as e:
            with lock:
                fails[rel] = fails.get(rel, 0) + 1
                if fails[rel] == 1:
                    print(f" R2: {rel}: {str(e)[:150]}")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(move, todo))
    library.save_json(STATE, s, indent=1)
    left = len(todo) - done["n"]
    print(f"R2: moved {done['n']} files ({done['bytes'] / 1e6:.0f} MB) off GitHub; {len(up)} on R2 in total, "
          f"{left} still on GitHub" + (" (time budget used up; the rest move next run)" if stop.is_set() else "")
          + (f"; Cloudflare asked to slow down {done['slow']} times" if done["slow"] else ""))
    return done["n"]


def status():
    s, todo = state(), waiting()
    up = s.get("up") or {}
    print(f"On R2: {len(up)} files, {sum(up.values()) / 1e6:.0f} MB ({s.get('base') or 'no public address yet'})")
    print(f"Still on GitHub: {len(todo)} files, {sum(x[2] for x in todo) / 1e6:.0f} MB")
    print(f"Failing: {sum(1 for v in (s.get('_failed') or {}).values() if v >= 5)} gave up after 5 tries")


if __name__ == "__main__":
    status() if "--status" in sys.argv else run()
