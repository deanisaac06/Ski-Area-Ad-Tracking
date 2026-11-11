"""Gemini (free tier) for two jobs:
  tag_new_ads()  - reads each ad once (copy, or the saved image when there's no copy) and stores
                   campaign type, themes, prices, deadline, a one-line offer and anything that stands out
                   in data/tags.json. Ads it hasn't reached yet use keyword rules (library.rule_tags).
  summarize()    - the strategist write-up at the top of the weekly report.
Needs the GEMINI_API_KEY secret; without it everything falls back to the keyword rules.
"""
import base64
import json
import os
import re
import time

import requests

import library

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]                 # the weekly summary
TAG_MODELS = ["gemini-flash-lite-latest", "gemini-3.8-flash-lite", "gemini-flash-latest"]   # tagging: simple, high volume
PACE = 6.5            # seconds between calls - keeps under the free tier's per-minute limit
TEXT_BATCH, IMAGE_BATCH = 12, 6

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

Return a JSON array only.

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
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\[.*\]", text, re.S)
        data = json.loads(m.group(0)) if m else []
    return [d for d in data if isinstance(d, dict) and d.get("k")]


def keep(t):
    camps = [c for c in (t.get("camp") or []) if c in library.CAMPAIGNS][:2]
    return {"camp": camps or ["Brand & general"], "themes": [x for x in (t.get("themes") or []) if x in library.THEMES][:4],
            "prices": [str(p) for p in (t.get("prices") or [])][:4],
            "deadline": t.get("deadline") if re.fullmatch(r"\d{4}-\d\d-\d\d", str(t.get("deadline") or "")) else "",
            "offer": str(t.get("offer") or "")[:120], "text": str(t.get("text") or "")[:300],
            "stand": str(t.get("stand") or "")[:160], "src": "ai", "ai": True}


def tag_new_ads(max_calls=60, max_seconds=1200):
    if not key():
        print("AI tags skipped (no GEMINI_API_KEY) - using keyword rules")
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
                                             year=year, next_year=year + 1, ads="\n".join(lines))
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
        out = ask(parts, deadline, models=TAG_MODELS, json_out=True)
        if not out:
            fails += 1
            if fails >= 3:
                print("  tagging stopped - Gemini not answering; the rest wait for the next run")
                break
            time.sleep(30)
            continue
        fails = 0
        try:
            got = parse(out)
        except Exception as e:
            print("  couldn't read Gemini's answer:", str(e)[:100])
            continue
        wanted = {a["key"] for a in batch}
        for t in got:
            if t["k"] in wanted:
                tags[t["k"]] = keep(t)
                done += 1
        library.save_json(library.TAGS, tags)
        time.sleep(PACE)
    print(f"AI tags: tagged {done} ads in {calls} calls ({len(todo) - done} left for later runs)")
    return done


def summarize(prompt, max_seconds=900):
    if not key():
        return None
    return ask([{"text": prompt}], time.time() + max_seconds, system=AI_SYSTEM, temperature=0.5)
