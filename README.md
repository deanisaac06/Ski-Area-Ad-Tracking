# Ski Area Ad Tracking

A self-updating library of the Meta (Facebook/Instagram) and Google ads run by 20 pilot US ski resorts,
with a weekly emailed report.

**Site:** https://deanisaac06.github.io/Ski-Area-Ad-Tracking/ (GitHub Pages, served from `docs/`)

## What runs when (`.github/workflows/weekly.yml`, hourly on Mon/Tue/Thu/Fri; `run.py` only does what's due)
| Step | When |
|---|---|
| Meta collection (active US ads per resort page, via Apify) | Mondays + Thursdays |
| Google collection: free listing from Google's Ads Transparency Center (`gfree.py`), then Apify only for ads not already in the library | Mondays |
| Save images to `docs/media/` (Meta links expire in ~5 days), then move them and the videos to Cloudflare R2 (`r2.py`) so the site stays under GitHub Pages' 1 GB limit | every run |
| AI tags with Gemini (Groq/Cloudflare while Gemini is busy): campaign type, offer, prices, deadline, standouts | every run, newest first |
| Catch-up: if tags or video notes are still waiting and the run made progress, it queues a `tag` run (no collection, up to 200 AI calls) | right after any run; progress in `data/backlog.json` |
| Weekly report: emailed + saved to `docs/reports/` | Mondays ~6–7am Pacific; if the AI summary fails it retries hourly and sends without it after 24h |
| Rebuild the site data (`docs/data.js`) and spreadsheets (`data/ads_*.csv`) | every run |

Run it by hand: **Actions → Ad library (weekly) → Run workflow**, with action `auto`, `collect-meta`,
`collect-google`, `collect-both`, `report`, `build` or `tag` (clear the AI backlog without collecting).

## Files
- `collect.py`: Apify runs, saving `data/raw/<platform>/<date>/<resort>.json.gz` and costs in `data/runs.csv`
- `library.py`: rebuilds every ad from the raw downloads, plus the winner score → `docs/data.js`, `data/ads_*.csv`
- `media.py`: image copies; `ai.py`: Gemini tags and summary; `report.py`: weekly report; `mailer.py`: Gmail
- `resorts.csv`: resorts (`pilot=yes` are tracked)
- `meta_pages.csv`: Facebook page ids found by hand for resorts the atlas had none for (one row per page; grouped rows like Liberty / Roundtop / Whitetail list one per resort)
- `r2.py`: moves saved videos and pictures to Cloudflare R2 (`python r2.py --status` shows how much is where)
- `docs/index.html` + `docs/app.js`: the site

## Secrets
`APIFY_TOKEN` (required), `GEMINI_API_KEY` (AI tags + summary), `SMTP_USER`, `SMTP_PASS`, `REPORT_TO`
(Gmail sender, app password, recipient; same values as the Instagram tracker).

## Costs
Apify free plan ($5/month credit): Meta is close to free. Google is about $0.002 per ad, and only ads the library doesn't have yet are paid for:
the list of each resort's ads (and the last-shown dates of ones we already have) comes free from `gfree.py`.
