# Ski Area Ad Tracking

A self-updating library of the Meta (Facebook/Instagram) and Google ads run by 20 pilot US ski resorts,
with a weekly emailed report.

**Site:** https://deanisaac06.github.io/Ski-Area-Ad-Tracking/ (GitHub Pages, served from `docs/`)

## What runs when (`.github/workflows/weekly.yml`, hourly on Mon/Tue/Thu/Fri; `run.py` only does what's due)
| Step | When |
|---|---|
| Meta collection (active US ads per resort page, via Apify) | Mondays + Thursdays |
| Google collection (ads shown since the last check, via Apify) | Mondays |
| Save images to `docs/media/` (Meta links expire in ~5 days) | every run |
| AI tags with Gemini: campaign type, offer, prices, deadline, standouts | every run, newest first |
| Weekly report: emailed + saved to `docs/reports/` | Mondays ~6–7am Pacific; if the AI summary fails it retries hourly and sends without it after 24h |
| Rebuild the site data (`docs/data.js`) and spreadsheets (`data/ads_*.csv`) | every run |

Run it by hand: **Actions → Ad library (weekly) → Run workflow**, with action `auto`, `collect-meta`,
`collect-google`, `collect-both`, `report` or `build`.

## Files
- `collect.py`: Apify runs, saving `data/raw/<platform>/<date>/<resort>.json.gz` and costs in `data/runs.csv`
- `library.py`: rebuilds every ad from the raw downloads, plus the winner score → `docs/data.js`, `data/ads_*.csv`
- `media.py`: image copies; `ai.py`: Gemini tags and summary; `report.py`: weekly report; `mailer.py`: Gmail
- `resorts.csv`: resorts (`pilot=yes` are tracked)
- `docs/index.html` + `docs/app.js`: the site

## Secrets
`APIFY_TOKEN` (required), `GEMINI_API_KEY` (AI tags + summary), `SMTP_USER`, `SMTP_PASS`, `REPORT_TO`
(Gmail sender, app password, recipient; same values as the Instagram tracker).

## Costs
Apify free plan ($5/month credit): Meta is close to free. Google is about $0.002 per ad, capped at 50 per resort
per check, and only ads shown since the last check are pulled.
