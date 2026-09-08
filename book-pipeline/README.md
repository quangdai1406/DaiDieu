# Book Publishing Pipeline

Automates the daily workflow you already do by hand (per `Writing Books/Promt for AI.docx`
in your Drive): pick a topic, draft chapters with an LLM, write a back-cover blurb and
author bio, then publish to Kindle Direct Publishing (KDP).

## Why this isn't "fully autonomous, no review"

Two hard constraints shape the design:

1. **KDP has no public API.** Amazon does not offer programmatic publishing. Any
   "auto-upload" has to drive the KDP web dashboard with browser automation
   (Playwright) using your login session — there is no official, sanctioned way
   around this.
2. **You chose the review-gated flow.** Publishing AI-drafted, trend-chased books
   to a live account with zero human review daily is also what gets KDP accounts
   suspended (their content guidelines flag low-effort/AI spam patterns), so the
   pipeline stops at a **review package**, not a live listing.

Every night's run produces a folder in `output/YYYY-MM-DD-slug/` with the manuscript,
covers, and pricing recommendation. You approve it (or send edit notes back), then a
separate `scripts/kdp_upload.py` (Playwright, run manually with `--confirm`) drives the
actual KDP dashboard.

## Pipeline stages (`scripts/orchestrator.py`)

1. **`trend_research.py`** — pulls candidate topics (Google Trends, Amazon Best
   Sellers/Movers & Shakers in your target categories, Reddit/Google News) and scores
   them against your existing catalog (from `Writing Books/` in Drive) to avoid
   duplicates and stay in your proven genres (business/investing/tax, DIY tech/Raspberry
   Pi builds, etc. — see `config/niches.yaml`).
2. **`write_book.py`** — runs your existing prompt chain (title → TOC → per-chapter
   1500-2000 word sections → intro → back cover → author bio → keywords) against the
   Claude API. Template lives in `prompts/book_prompts.md`, lifted directly from your
   `Promt for AI.docx`.
3. **`generate_cover.py`** — builds front/back cover as an HTML canvas (title, subtitle,
   author, back-cover blurb, barcode placeholder) and rasterizes to KDP's required
   300 DPI PNG/PDF trim sizes.
4. **`pricing.py`** — computes KDP royalty (35%/70% tiers, printing cost for paperback,
   $2.99–$9.99 sweet spot for the 70% royalty band) against comparable titles' prices in
   the same category to recommend a price that maximizes expected royalty × conversion,
   not just royalty per unit.
5. **`kdp_prepare.py`** — assembles the review package: manuscript (.docx via the repo's
   docx pipeline), covers, title/subtitle/description/keywords/categories, and the price
   recommendation with reasoning, into `output/<date>-<slug>/`.
6. **`kdp_upload.py`** (manual, `--confirm` required) — Playwright script that logs into
   KDP Bookshelf and fills the "Create new title" form from the approved package. Never
   run by the scheduler; you run it after reviewing stage 5's output.

## Setup

```
cd book-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, KDP_EMAIL/KDP_PASSWORD, trend API keys
playwright install chromium   # only needed for kdp_upload.py
```

`config/niches.yaml` — edit to match the genres in your Drive catalog (pull an initial
list with `python scripts/trend_research.py --catalog-only` once Drive sync is wired up).

## Daily run

`scripts/orchestrator.py` runs stages 1–5 and writes the review package. Nothing touches
your live KDP account. Schedule it for 2:00 AM in your local timezone with cron/Task
Scheduler/a Claude Code Routine — see "Scheduling" below.

## Scheduling (runs on your own machine, Eastern time)

This has to run from your machine, not a cloud sandbox — `trend_research.py` calls
`trends.google.com` directly, which many hosted environments block at the network policy
level. Cron on your machine:

```
crontab -e
```

Add (adjust the repo path to wherever you clone `daidieu`):

```
0 2 * * * cd /path/to/daidieu/book-pipeline && .venv/bin/python scripts/orchestrator.py >> output/cron.log 2>&1
```

Cron runs in your machine's local timezone by default — confirm with `timedatectl` (Linux)
or Date & Time settings (Mac/Windows) that it's set to Eastern, or the run will fire at the
wrong hour.

Until `ANTHROPIC_API_KEY` is set in `.env`, the run will get through stage 1 (Google
Trends — works now, no key needed) and then fail loudly at stage 2 (`write_book.py`)
rather than silently producing nothing — check `output/cron.log` after the first run.

## Status

This is a working scaffold, not yet wired to live credentials or your Drive catalog.
Remaining before the first real run:
- [ ] Fill in `.env` with real API keys
- [ ] Point `trend_research.py` at real trend sources (currently stubs — see TODOs)
- [ ] Confirm `config/niches.yaml` against your actual back-catalog
- [ ] Dry-run `kdp_upload.py` against a KDP sandbox/test title before trusting it on a real one
