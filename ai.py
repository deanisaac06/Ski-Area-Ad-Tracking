"""AI for two jobs - Gemini (free tier) first; when it's overloaded, Groq covers for GEMINI_COOLDOWN (then Gemini again), then
Cloudflare Workers AI (both free tiers, OpenAI-style APIs):
  tag_new_ads()  - reads each ad once (copy, or the saved image when there's no copy) and stores
                   campaign type, themes, prices, deadline, a one-line offer and anything that stands out
                   in data/tags.json. Ads it hasn't reached yet use keyword rules (library.rule_tags).
  summarize()    - the strategist write-up at the top of the weekly report.
Secrets: GEMINI_API_KEY; GROQ_API_KEY; CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN. Any missing provider is
skipped; with none at all, tags fall back to keyword rules. Gemini's outage clock is kept in data/ai_status.json.
"""
import base64
import json
import os
import re
import time
from datetime import datetime, timezone

import requests

import library
import taxonomy as TX

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]                 # the weekly summary
TAG_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]   # tagging: simple, high volume
PACE = 6.5            # seconds between calls - keeps under the free tier's per-minute limit
TEXT_BATCH, IMAGE_BATCH = 12, 5          # Groq accepts at most 5 images per request
BACKUP_TEXT_BATCH, BACKUP_IMAGE_BATCH = 6, 5   # smaller text batches while Groq/Cloudflare answer: their free tier allows ~8k tokens/min
BACKUP_MAX_TOKENS = 2048                 # Groq counts max_tokens against the per-minute limit, so ask for no more than needed
BACKUP_RETRY = 90                        # a backup that didn't answer gets another try after this many seconds
FALLBACK_AFTER = 0                     # seconds Gemini must be failing before Groq / Cloudflare take over
GEMINI_COOLDOWN = 300  # after Gemini fails, Groq answers for 5 min, then Gemini gets another try;
GEMINI_COOLDOWN_MAX = 3600   # each further failure in the same run doubles the wait, up to an hour
AI_STATUS = os.path.join(library.DATA, "ai_status.json")
GROQ_URL = "https://api.groq.com/openai/v1"
# Preferred Groq models, in order. Names Groq has retired are skipped automatically: each run reads Groq's live model
# list, keeps the ones below that still exist, then adds any other live models that look suitable.
GROQ_TEXT = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b"]
GROQ_VISION = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]
GROQ_SKIP = re.compile(r"whisper|tts|guard|playai|orpheus|embed|prompt-guard|safeguard|compound|allam", re.I)
GROQ_VISION_HINT = re.compile(r"llama-4|vision|scout|maverick|-vl|vl-", re.I)
CF_TEXT = ["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-4-scout-17b-16e-instruct"]
CF_VISION = ["@cf/meta/llama-4-scout-17b-16e-instruct"]

TAG_PROMPT = """You are tagging ski resort ads for a searchable ad library. For EACH ad below return one JSON object.

Fields:
- "k": the ad's key, copied exactly
- "camp": 1-2 campaign types, ONLY from: {campaigns}
- "themes": 0-4, ONLY from: {themes}
- "prices": dollar amounts that appear, as written (e.g. "$169"), else []
- "deadline": an offer deadline as YYYY-MM-DD if the ad states one (ads run in {year}/{next_year}), else ""
- "offer": the concrete offer in under 12 words (e.g. "Kids ski free with 2-night stay"), else ""
- "text": for image ads only, the main words printed on the image (under 30 words), else ""
- "stand": if the ad is markedly different from typical resort ads (unusual idea, format, partnership, tone), one short reason; else ""
- "obj": the funnel stage, ONE of: Awareness (brand, inspiration, video with no direct ask), Consideration (explore, learn more, plan a trip), Conversion (buy, book, sign up, a price or a deadline)
- "aud": 1-2 audiences the ad speaks to, ONLY from: {audiences}
- "ot": 1-2 offer types, ONLY from: {offer_types} (use "No offer" when there is none)

Return JSON only: an object of the form {{"ads": [ ...one object per ad... ]}}.

ADS:
{ads}"""

AI_SYSTEM = ("You are a senior paid-media strategist at an agency that works with ski resorts. You write sharp, "
             "specific, plain-English analysis for a marketer who knows the industry. No fluff, no hedging, no bullet lists.")


def key():
    return os.environ.get("GEMINI_API_KEY")


NO_THINKING = {}            # models that rejected the thinking setting (then sent without it)


def call(model, parts, deadline, json_out=False, system=None, temperature=0.3, think=True):
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 8192}}
    if json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
        if model not in NO_THINKING:     # tagging is simple - long "thinking" just makes requests time out
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 256}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    r = None
    for attempt in range(3):
        try:
            r = requests.post(f"{GEMINI_URL}/models/{model}:generateContent",
                              timeout=max(20, min(100 if json_out else 180, deadline - time.time())),
                              headers={"x-goog-api-key": key(), "Content-Type": "application/json"}, json=body)
        except requests.exceptions.Timeout:
            if attempt < 1 and time.time() + 60 < deadline:
                print(f"  {model}: timed out, retrying")
                continue
            raise
        if r.status_code == 400 and "thinking" in r.text.lower() and model not in NO_THINKING:
            NO_THINKING[model] = True
            return call(model, parts, deadline, json_out, system, temperature)
        if r.status_code in (429, 500, 503) and attempt < 1 and time.time() + 30 < deadline:
            print(f"  {model}: busy (HTTP {r.status_code}), retrying in 20s")
            time.sleep(20)
            continue
        break
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if text:
            return text
    except Exception:
        pass
    print(f"  {model}: HTTP {r.status_code} {r.text[:200]!r}")
    return None


def flash_models():
    try:
        r = requests.get(f"{GEMINI_URL}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key()}, timeout=30)
        names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-lite)?", n)]
        return sorted(flash, key=lambda n: (float(re.findall(r"\d+(?:\.\d+)?", n)[0]), "lite" not in n), reverse=True)
    except Exception:
        return []


def ask(parts, deadline, models=None, **kw):
    """Try the configured models, then whatever Flash models the key can see."""
    tried = []
    for m in (models or MODELS) + ["__discover__"]:
        for model in (flash_models()[:3] if m == "__discover__" else [m]):
            if model in tried or time.time() > deadline - 15:
                continue
            tried.append(model)
            try:
                out = call(model, parts, deadline, **kw)
            except Exception as e:
                print(f"  {model}: {str(e)[:150]}")
                out = None
            if out:
                return out
    return None


# ------------------------------------------------------------------ Groq / Cloudflare (OpenAI-style)
def to_messages(parts, system):
    images = [p for p in parts if "inline_data" in p]
    if images:
        content = []
        for p in parts:
            if "text" in p:
                content.append({"type": "text", "text": p["text"]})
            else:
                d = p["inline_data"]
                content.append({"type": "image_url", "image_url": {"url": f"data:{d['mime_type']};base64,{d['data']}"}})
    else:
        content = "\n".join(p["text"] for p in parts)
    msgs = [{"role": "system", "content": system}] if system else []
    return msgs + [{"role": "user", "content": content}], bool(images)


DEAD_MODELS = set()          # backup models that answered "does not exist" this run
OCR_ONLY = set()             # backups that tagged image ads from OCR words, without seeing the picture
GROQ_LIVE = None             # (text models, vision models) from Groq's live list, read once per run


def groq_models():
    """GROQ_TEXT / GROQ_VISION minus retired names, plus other live chat models as a last resort."""
    global GROQ_LIVE
    if GROQ_LIVE is None:
        GROQ_LIVE = (GROQ_TEXT, GROQ_VISION)
        try:
            r = requests.get(f"{GROQ_URL}/models", headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, timeout=30)
            live = [m["id"] for m in r.json().get("data", []) if m.get("active", True)]
            if live:
                chat = [m for m in live if not GROQ_SKIP.search(m)]
                text = [m for m in GROQ_TEXT if m in live] + [m for m in chat if m not in GROQ_TEXT and not GROQ_VISION_HINT.search(m)]
                vision = [m for m in GROQ_VISION if m in live] + [m for m in chat if m not in GROQ_VISION and GROQ_VISION_HINT.search(m)]
                gone = [m for m in GROQ_TEXT + GROQ_VISION if m not in live]
                if gone:
                    print(f"  Groq: retired model(s) skipped: {', '.join(gone)}")
                GROQ_LIVE = (text[:4], vision[:3])
                print(f"  Groq models this run - text: {', '.join(GROQ_LIVE[0]) or 'none'}; images: {', '.join(GROQ_LIVE[1]) or 'none'}")
        except Exception as e:
            print("  Groq: couldn't read the model list:", str(e)[:120])
    return GROQ_LIVE


def wait_hint(r):
    """Seconds Groq/Cloudflare ask us to wait after a 429 (retry-after header or 'try again in 12.3s')."""
    try:
        if r.headers.get("retry-after"):
            return float(r.headers["retry-after"])
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", r.text)
        if m:
            secs = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
            return secs + 60 * int(m.group(1) or 0)
    except Exception:
        pass
    return 20


def openai_provider(prov):
    if prov == "groq" and os.environ.get("GROQ_API_KEY"):
        text, vision = groq_models()
        return f"{GROQ_URL}/chat/completions", os.environ["GROQ_API_KEY"], text, vision
    acct, tok = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if prov == "cloudflare" and acct and tok:
        return (f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1/chat/completions", tok, CF_TEXT, CF_VISION)
    return None


def openai_call(prov, parts, deadline, json_out=False, system=None, temperature=0.3):
    conf = openai_provider(prov)
    if not conf:
        return None
    url, token, text_models, vision_models = conf
    msgs, has_images = to_messages(parts, system)
    models = vision_models if has_images else text_models
    if has_images and not [m for m in vision_models if (prov, m) not in DEAD_MODELS]:
        # no picture-reading model on this backup: send the words read off each picture (OCR) instead
        msgs, has_images = to_messages([p for p in parts if "text" in p], system)
        models = text_models
        OCR_ONLY.add(prov)
    for model in models:
        if time.time() > deadline - 15:
            break
        if (prov, model) in DEAD_MODELS:
            continue
        body = {"model": model, "messages": msgs, "temperature": temperature,
                "max_tokens": BACKUP_MAX_TOKENS if json_out else 4096}
        if json_out and prov == "groq":
            body["response_format"] = {"type": "json_object"}
        for attempt in range(4):
            try:
                r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body,
                                  timeout=max(20, min(120, deadline - time.time())))
            except requests.exceptions.RequestException as e:
                print(f"  {prov} {model}: {str(e)[:120]}")
                break
            if r.status_code == 400 and "response_format" in body:
                body.pop("response_format")
                continue
            if r.status_code == 404 or (r.status_code == 400 and "decommissioned" in r.text):
                DEAD_MODELS.add((prov, model))
                print(f"  {prov} {model}: no longer available - skipped for the rest of the run")
                break
            if r.status_code == 413 or (r.status_code == 429 and "tokens per day" in r.text.lower()):
                print(f"  {prov} {model}: HTTP {r.status_code} (request too big or daily limit) - next model")
                break
            if r.status_code in (429, 500, 503) and attempt < 3:
                wait = min(65, max(5, wait_hint(r) + 1)) if r.status_code == 429 else 20
                if time.time() + wait + 30 > deadline:
                    break
                print(f"  {prov} {model}: busy (HTTP {r.status_code}), retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            try:
                text = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if text:
                    return text
            except Exception:
                pass
            print(f"  {prov} {model}: HTTP {r.status_code} {r.text[:200]!r}")
            break
    return None


class Router:
    """Gemini first. When it fails, backups answer for GEMINI_COOLDOWN seconds, then Gemini again: Groq,
    then Cloudflare. Within one run a provider that fails isn't hammered again."""

    def __init__(self):
        self.st = library.load_json(AI_STATUS, {})
        self.failed = {}  # provider -> time it may be tried again
        self.gemini_retry = 0  # when Gemini fails, the backup answers for GEMINI_COOLDOWN, then Gemini gets another try
        self.gemini_fails = 0  # Gemini failures in a row this run - each one doubles the cooldown
        self.used = {}  # answers per provider this run, e.g. {"gemini": 30, "groq": 6}

    def save(self):
        library.save_json(AI_STATUS, self.st, indent=1)

    def count(self, prov):
        self.used[prov] = self.used.get(prov, 0) + 1

    def split(self):
        return " / ".join(f"{p.capitalize()} {n}" for p, n in sorted(self.used.items(), key=lambda x: -x[1])) or "none"

    def gemini_down_for(self):
        since = self.st.get("gemini_down_since")
        return (datetime.now(timezone.utc) - datetime.fromisoformat(since)).total_seconds() if since else 0

    def any_provider(self):
        return bool(key() or openai_provider("groq") or openai_provider("cloudflare"))

    def ask(self, parts, deadline, json_out=False, system=None, temperature=0.3, gemini_models=None):
        """Returns (text, provider) - text None and provider 'wait' while Gemini is down for under FALLBACK_AFTER seconds."""
        if key() and time.time() >= self.gemini_retry:
            sub = min(deadline, time.time() + (300 if json_out else 600))
            out = ask(parts, sub, models=gemini_models, json_out=json_out, system=system, temperature=temperature)
            if out:
                if self.st.get("gemini_down_since"):
                    self.st["gemini_down_since"] = None
                    self.save()
                self.count("gemini")
                self.gemini_fails = 0
                return out, "gemini"
            wait = min(GEMINI_COOLDOWN_MAX, GEMINI_COOLDOWN * 2 ** self.gemini_fails)
            self.gemini_fails += 1
            self.gemini_retry = time.time() + wait
            print(f"  Gemini busy - backup answers for {wait // 60} min, then Gemini again")
            if not self.st.get("gemini_down_since"):
                self.st["gemini_down_since"] = datetime.now(timezone.utc).isoformat()
                self.save()
        if key() and self.gemini_down_for() < FALLBACK_AFTER:
            print(f"  Gemini unavailable for {self.gemini_down_for() / 60:.0f} min - waiting before using the backup")
            return None, "wait"
        # pictures: Cloudflare first (its model sees the image; Groq has no picture model now and reads OCR words)
        order = ("cloudflare", "groq") if any("inline_data" in p for p in parts) else ("groq", "cloudflare")
        for prov in order:
            if time.time() < self.failed.get(prov, 0) or not openai_provider(prov):
                continue
            OCR_ONLY.discard(prov)
            out = openai_call(prov, parts, deadline, json_out=json_out, system=system, temperature=temperature)
            if out:
                self.count(prov)
                return out, (prov + "-ocr" if prov in OCR_ONLY else prov)
            self.failed[prov] = time.time() + BACKUP_RETRY
        return None, None

    def on_backup(self):
        """True while Gemini is cooling down and a backup is answering - tagging uses smaller batches then."""
        return bool(key()) and time.time() < self.gemini_retry or not key()


ROUTER = None


def router():
    global ROUTER
    if ROUTER is None:
        ROUTER = Router()
    return ROUTER


# ------------------------------------------------------------------ tagging
def ad_line(a):
    bits = [f'k={a["key"]}', a["n"], a["p"], a["kind"]]
    for label, field in (("headline", "title"), ("copy", "body"), ("link text", "desc"), ("button", "cta"), ("landing", "link")):
        if a.get(field):
            bits.append(f"{label}: {str(a[field])[:500]}")
    if a.get("headlines") and len(a["headlines"]) > 1:
        bits.append("other headlines: " + " / ".join(a["headlines"][1:]))
    return " | ".join(bits)


def parse(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        data = json.loads(m.group(0)) if m else []
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [data])
    return [d for d in data if isinstance(d, dict) and d.get("k")]


def keep(t, provider="gemini"):
    camps = [c for c in (t.get("camp") or []) if c in library.CAMPAIGNS][:2]
    return {"camp": camps or ["Brand & general"], "themes": [x for x in (t.get("themes") or []) if x in library.THEMES][:4],
            "prices": [str(p) for p in (t.get("prices") or [])][:4],
            "deadline": t.get("deadline") if re.fullmatch(r"\d{4}-\d\d-\d\d", str(t.get("deadline") or "")) else "",
            "offer": str(t.get("offer") or "")[:120], "text": str(t.get("text") or "")[:300],
            "stand": str(t.get("stand") or "")[:160], "obj": t.get("obj") if t.get("obj") in TX.FUNNEL else "",
            "aud": [x for x in (t.get("aud") or []) if x in TX.AUDIENCES][:3], "ot": [x for x in (t.get("ot") or []) if x in TX.OFFER_TYPES][:2], "src": "ai", "ai": True, "by": provider}


OCR_CACHE = None


def image_words(path):
    """Words printed on a saved ad picture (Tesseract OCR; reuses vision.py's readings). Lets text-only backup
    models tag image ads when no backup vision model is available."""
    global OCR_CACHE
    try:
        import media as M
        import vision
        from PIL import Image
        if OCR_CACHE is None:
            OCR_CACHE = (library.load_json(os.path.join(library.DATA, "vision.json"), {}) or {}).get("ocr") or {}
        with Image.open(path) as im:
            im = M.to_rgb(im)
            fp = M.dhash(im)
            if fp not in OCR_CACHE:
                OCR_CACHE[fp] = vision.read(im)
            return (OCR_CACHE[fp] or "").strip()
    except Exception:
        return ""


def tag_backlog():
    """Ads still waiting for AI tags (same rule tag_new_ads uses)."""
    ads, _ = library.build_ads()
    tags = library.load_json(library.TAGS, {})
    media = library.load_json(library.MEDIA, {})
    return sum(1 for k, a in ads.items() if k not in tags and (a.get("title") or a.get("body") or k in media))


def tag_new_ads(max_calls=60, max_seconds=1200):
    rt = router()
    if not rt.any_provider():
        print("AI tags skipped (no AI keys) - using keyword rules")
        return 0
    ads, _ = library.build_ads()
    tags = library.load_json(library.TAGS, {})
    media = library.load_json(library.MEDIA, {})
    for k, a in ads.items():
        a["key"] = k
    has_text = lambda a: a.get("title") or a.get("body")
    todo = [a for k, a in ads.items() if k not in tags and (has_text(a) or k in media)]
    todo.sort(key=lambda a: a.get("start") or "", reverse=True)          # newest first
    queues = {"text": [a for a in todo if has_text(a)], "image": [a for a in todo if not has_text(a)]}
    print(f"AI tags: {len(todo)} ads to tag ({len(queues['text'])} with copy, {len(queues['image'])} image-only), "
          f"up to {max_calls} calls this run")
    year = int(time.strftime("%Y"))
    prompt = lambda lines: TAG_PROMPT.format(campaigns=", ".join(library.CAMPAIGNS), themes=", ".join(library.THEMES),
                                             year=year, next_year=year + 1, audiences=", ".join(TX.AUDIENCES), offer_types=", ".join(TX.OFFER_TYPES), ads="\n".join(lines))
    deadline = time.time() + max_seconds
    done, calls, fails = 0, 0, 0
    while queues["text"] or queues["image"]:
        if calls >= max_calls or time.time() > deadline - 60:
            break
        kind = "text" if queues["text"] else "image"
        backup = rt.on_backup()          # Gemini resting -> Groq/Cloudflare, which need smaller requests
        size = {"text": BACKUP_TEXT_BATCH if backup else TEXT_BATCH, "image": BACKUP_IMAGE_BATCH if backup else IMAGE_BATCH}[kind]
        batch = queues[kind][:size]
        if kind == "text":
            parts = [{"text": prompt([ad_line(a) for a in batch])}]
        else:
            lines = []
            for a in batch:
                words = image_words(os.path.join(library.DOCS, media[a["key"]]))
                lines.append(ad_line(a) + (f" | words on the image (OCR, may be messy): {words[:300]}" if words else "")
                             + " | (image below, in this order)")
            parts = [{"text": prompt(lines)}]
            for a in batch:
                with open(os.path.join(library.DOCS, media[a["key"]]), "rb") as f:
                    parts += [{"text": f"image for k={a['key']}:"},
                              {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(f.read()).decode()}}]
        calls += 1
        out, provider = rt.ask(parts, deadline, json_out=True, gemini_models=TAG_MODELS)
        if provider == "wait":
            print("  tagging paused until Gemini is back")
            break
        if not out:
            fails += 1
            if fails >= 4:
                print("  tagging stopped - no AI provider answered 4 times in a row; the rest wait for the next run")
                break
            pause = min(90, 30 * fails)
            if time.time() + pause > deadline - 60:
                break
            print(f"  no AI answered - waiting {pause}s, then trying again")
            time.sleep(pause)
            continue
        fails = 0
        try:
            got = parse(out)
        except Exception as e:
            print(f"  couldn't read {provider}'s answer:", str(e)[:100])
            queues[kind] = queues[kind][len(batch):] + batch   # try these again later, don't loop on them
            continue
        wanted = {a["key"] for a in batch}
        for t in got:
            if t["k"] in wanted:
                done += t["k"] not in tags
                tags[t["k"]] = keep(t, provider)
        queues[kind] = [a for a in queues[kind] if a["key"] not in tags]
        missed = [a for a in batch if a["key"] not in tags]
        if missed:                                         # answer skipped some: move them to the back
            queues[kind] = [a for a in queues[kind] if a not in missed] + missed
        library.save_json(library.TAGS, tags)
        time.sleep(PACE)
    left = len(queues["text"]) + len(queues["image"])
    print(f"AI tags: tagged {done} ads in {calls} calls - answered by {rt.split()} ({left} left for later runs)")
    return done


def summarize(prompt, max_seconds=900):
    rt = router()
    if not rt.any_provider():
        return None
    text, provider = rt.ask([{"text": prompt}], time.time() + max_seconds, system=AI_SYSTEM, temperature=0.5)
    if text:
        print(f"AI summary written by {provider}")
    return text
