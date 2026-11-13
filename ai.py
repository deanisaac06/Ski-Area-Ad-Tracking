"""AI for two jobs - Gemini (free tier) first; if Gemini has been unavailable for an hour, Groq, then
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
FALLBACK_AFTER = 0                     # seconds Gemini must be failing before Groq / Cloudflare take over
AI_STATUS = os.path.join(library.DATA, "ai_status.json")
GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_TEXT = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "meta-llama/llama-4-maverick-17b-128e-instruct"]
GROQ_VISION = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]
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


def openai_provider(prov):
    if prov == "groq" and os.environ.get("GROQ_API_KEY"):
        return f"{GROQ_URL}/chat/completions", os.environ["GROQ_API_KEY"], GROQ_TEXT, GROQ_VISION
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
    for model in (vision_models if has_images else text_models):
        if time.time() > deadline - 15:
            break
        body = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": 4096}
        if json_out and prov == "groq":
            body["response_format"] = {"type": "json_object"}
        for attempt in range(2):
            try:
                r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body,
                                  timeout=max(20, min(120, deadline - time.time())))
            except requests.exceptions.RequestException as e:
                print(f"  {prov} {model}: {str(e)[:120]}")
                break
            if r.status_code == 400 and "response_format" in body:
                body.pop("response_format")
                continue
            if r.status_code in (429, 500, 503) and attempt == 0 and time.time() + 30 < deadline:
                print(f"  {prov} {model}: busy (HTTP {r.status_code}), retrying in 20s")
                time.sleep(20)
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
    """Gemini first. Once Gemini has been failing for FALLBACK_AFTER seconds (tracked across runs), Groq,
    then Cloudflare. Within one run a provider that fails isn't hammered again."""

    def __init__(self):
        self.st = library.load_json(AI_STATUS, {})
        self.failed = set()
        self.gemini_retry = 0  # when Gemini fails, Groq answers for 15 minutes, then Gemini gets another try

    def save(self):
        library.save_json(AI_STATUS, self.st, indent=1)

    def gemini_down_for(self):
        since = self.st.get("gemini_down_since")
        return (datetime.now(timezone.utc) - datetime.fromisoformat(since)).total_seconds() if since else 0

    def any_provider(self):
        return bool(key() or openai_provider("groq") or openai_provider("cloudflare"))

    def ask(self, parts, deadline, json_out=False, system=None, temperature=0.3, gemini_models=None):
        """Returns (text, provider) - text None and provider 'wait' while Gemini is down for under an hour."""
        if key() and time.time() >= self.gemini_retry:
            sub = min(deadline, time.time() + (300 if json_out else 600))
            out = ask(parts, sub, models=gemini_models, json_out=json_out, system=system, temperature=temperature)
            if out:
                if self.st.get("gemini_down_since"):
                    self.st["gemini_down_since"] = None
                    self.save()
                return out, "gemini"
            self.gemini_retry = time.time() + 900
            if not self.st.get("gemini_down_since"):
                self.st["gemini_down_since"] = datetime.now(timezone.utc).isoformat()
                self.save()
        if key() and self.gemini_down_for() < FALLBACK_AFTER:
            print(f"  Gemini unavailable for {self.gemini_down_for() / 60:.0f} min - Groq takes over after 60 min")
            return None, "wait"
        for prov in ("groq", "cloudflare"):
            if prov in self.failed or not openai_provider(prov):
                continue
            out = openai_call(prov, parts, deadline, json_out=json_out, system=system, temperature=temperature)
            if out:
                return out, prov
            self.failed.add(prov)
        return None, None


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
    text_ads = [a for a in todo if has_text(a)]
    img_ads = [a for a in todo if not has_text(a)]
    batches = [("text", text_ads[i:i + TEXT_BATCH]) for i in range(0, len(text_ads), TEXT_BATCH)] + \
              [("image", img_ads[i:i + IMAGE_BATCH]) for i in range(0, len(img_ads), IMAGE_BATCH)]
    print(f"AI tags: {len(todo)} ads to tag ({len(text_ads)} with copy, {len(img_ads)} image-only), {len(batches)} calls")
    year = int(time.strftime("%Y"))
    prompt = lambda lines: TAG_PROMPT.format(campaigns=", ".join(library.CAMPAIGNS), themes=", ".join(library.THEMES),
                                             year=year, next_year=year + 1, audiences=", ".join(TX.AUDIENCES), offer_types=", ".join(TX.OFFER_TYPES), ads="\n".join(lines))
    deadline = time.time() + max_seconds
    done, calls, fails = 0, 0, 0
    for kind, batch in batches:
        if calls >= max_calls or time.time() > deadline - 60:
            break
        if kind == "text":
            parts = [{"text": prompt([ad_line(a) for a in batch])}]
        else:
            parts = [{"text": prompt([ad_line(a) + " | (image below, in this order)" for a in batch])}]
            for a in batch:
                with open(os.path.join(library.DOCS, media[a["key"]]), "rb") as f:
                    parts += [{"text": f"image for k={a['key']}:"},
                              {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(f.read()).decode()}}]
        calls += 1
        out, provider = rt.ask(parts, deadline, json_out=True, gemini_models=TAG_MODELS)
        if provider == "wait":
            print("  tagging paused until Gemini is back or the 60-minute fallback kicks in")
            break
        if not out:
            fails += 1
            if fails >= 2:
                print("  tagging stopped - no AI provider answering; the rest wait for the next run")
                break
            continue
        fails = 0
        try:
            got = parse(out)
        except Exception as e:
            print(f"  couldn't read {provider}'s answer:", str(e)[:100])
            continue
        wanted = {a["key"] for a in batch}
        for t in got:
            if t["k"] in wanted:
                tags[t["k"]] = keep(t, provider)
                done += 1
        library.save_json(library.TAGS, tags)
        time.sleep(PACE)
    print(f"AI tags: tagged {done} ads in {calls} calls ({len(todo) - done} left for later runs)")
    return done


def summarize(prompt, max_seconds=900):
    rt = router()
    if not rt.any_provider():
        return None
    text, provider = rt.ask([{"text": prompt}], time.time() + max_seconds, system=AI_SYSTEM, temperature=0.5)
    if text:
        print(f"AI summary written by {provider}")
    return text
