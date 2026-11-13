"""Moves saved Meta videos off GitHub to Cloudflare R2, so the site stays well under GitHub Pages' 1 GB limit.

media.py still saves each video to docs/media/v/<id>.mp4 first (the AI video notes and the health check use it
there). At the end of every run this uploads every video still in docs/media/v/ to the R2 bucket, checks that the
public copy is there and the same size, and only then deletes the GitHub copy. data/videos.json keeps the same
paths; url() turns a path into the R2 address once it's uploaded, and the site plays that.

One-time setup (by you, in Cloudflare):
  1. Cloudflare dashboard > R2 Object Storage: turn R2 on (free up to 10 GB stored; Cloudflare asks for a card
     but doesn't charge under the free limits).
  2. My Profile > API Tokens > Create token with "Workers R2 Storage: Edit" on this account, saved as the
     CLOUDFLARE_R2_TOKEN repository secret. CLOUDFLARE_ACCOUNT_ID is already set.
This script makes the bucket (R2_BUCKET, default ski-ad-videos) and turns on its public r2.dev address itself.
Until that's done, videos simply stay on GitHub and the run log says why. Nothing is deleted unless the R2 copy
checked out.

data/r2.json {"base": public address, "bucket": name, "up": {path: bytes}, "_failed": {path: tries}}
Run: python r2.py
"""
import os
import tempfile
import time

import requests

import library

STATE = os.path.join(library.DATA, "r2.json")
API = "https://api.cloudflare.com/client/v4"
BUCKET = os.environ.get("R2_BUCKET") or "ski-ad-videos"
MAX_MINUTES = 20
_state = {}


def state():
    if not _state:
        _state.update(library.load_json(STATE, {}))
    return _state


def url(rel):
    """The address the site should use for a saved video: R2 once it's uploaded, else the GitHub copy."""
    s = state()
    if rel and s.get("base") and rel in (s.get("up") or {}):
        return s["base"].rstrip("/") + "/" + rel.split("/")[-1]
    return rel or ""


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
    print(f" R2: videos are served from {base}")
    return base


def run():
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_R2_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
    vdir = os.path.join(library.DOCS, "media", "v")
    local = sorted(f for f in os.listdir(vdir) if f.endswith(".mp4")) if os.path.isdir(vdir) else []
    if not local:
        print("R2: no videos waiting to move off GitHub")
        return 0
    if not (acct and token):
        print(f"R2: {len(local)} videos stay on GitHub - CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_R2_TOKEN not set")
        return 0
    try:
        base = setup(acct, token)
    except Exception as e:
        print(f"::warning::R2 isn't ready, so {len(local)} videos stay on GitHub for now: {str(e)[:200]}")
        return 0
    s = state()
    up, fails = s.setdefault("up", {}), s.setdefault("_failed", {})
    moved, size, t0 = 0, 0, time.time()
    for name in local:
        if time.time() - t0 > MAX_MINUTES * 60:
            print(" R2: time budget used up; the rest move next run")
            break
        rel, path = "media/v/" + name, os.path.join(vdir, name)
        if fails.get(rel, 0) >= 5:
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
            _ok(requests.put(f"{API}/accounts/{acct}/r2/buckets/{BUCKET}/objects/{name}",
                             headers={**_h(token), "Content-Type": "video/mp4"}, data=data, timeout=180))
            chk = requests.head(base.rstrip("/") + "/" + name, timeout=60)
            if chk.status_code != 200 or int(chk.headers.get("content-length") or -1) != len(data):
                raise RuntimeError(f"public copy check failed (HTTP {chk.status_code})")
            up[rel] = len(data)
            os.remove(path)  # the GitHub copy; the site now plays the R2 one
            fails.pop(rel, None)
            moved += 1
            size += len(data)
        except Exception as e:
            fails[rel] = fails.get(rel, 0) + 1
            if fails[rel] == 1:
                print(f" R2: {name}: {str(e)[:150]}")
        if moved and moved % 25 == 0:
            library.save_json(STATE, s, indent=1)
    library.save_json(STATE, s, indent=1)
    print(f"R2: moved {moved} videos ({size / 1e6:.0f} MB) off GitHub; {len(up)} on R2 in total, "
          f"{len(local) - moved} still on GitHub")
    return moved


if __name__ == "__main__":
    run()
