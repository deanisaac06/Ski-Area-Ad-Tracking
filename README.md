# Ski Area Ad Tracking

Collects the ads US ski resorts run on Meta (Facebook/Instagram) and Google, as the first step toward a searchable resort ad library (plan: `ad-library-tracker-plan.md` in the Claude project).

## Pilot (20 resorts)
- `resorts.csv` - the 20 pilot resorts from the Ski Area Ad Atlas (top-ranked US prospects with both a Meta page ID and a domain).
- `collect.py` - one Apify run per resort per platform:
  - Meta: `curious_coder/facebook-ads-library-scraper` on the resort's Ad Library page (US, active ads). Meta only shows US ads while they run, so history builds from the first check.
  - Google: `silva95gustavo/google-ads-scraper` on the resort's domain (US). Google keeps past ads, so this also backfills.
- Output in `data/`: `ads_meta.csv`, `ads_google.csv` (one row per ad, with first/last seen), `runs.csv` (every Apify run and its cost), and the raw Apify output in `data/raw/` for checking fields.

Run it: Actions → **Collect ads (pilot)** → Run workflow. Needs the `APIFY_TOKEN` repository secret.

## Next (after the pilot)
Media saved to Cloudflare R2, AI tags (Gemini), the winner score, a weekly schedule, all US resorts, and the search site.
