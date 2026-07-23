# PartScout — Cross-Border Vehicle Parts Matcher

## What this is

A pipeline that monitors Nordic/Baltic motorcycle & car forums for **want-to-buy (WTB)** posts and marketplaces for **for-sale (FS)** listings, extracts structured intent with an LLM regardless of language (FI/SV/NO/DA/ET/LV/LT/PL/DE/EN), matches buyers to sellers across borders, and emails match digests.

Example target outcome: a Spanish Harley forum WTB for a front fender dust guard matches an FS listing on Nettimoto Finland.

## Architecture

```
[Source Adapters] → [Raw Posts Queue] → [LLM Extractor] → [Postgres]
                                                              ↓
[Matcher (part-no exact → embedding fuzzy → LLM verify)] → [Match Table] → [Email Digest]
```

## Stack (do not deviate without asking)

- Python 3.12, managed with `uv`
- Postgres 16 + pgvector extension (single DB for relational + vector)
- Scrapy for static/server-rendered sources; Playwright only where required
- Anthropic API: Haiku-class model for extraction & match verification (structured JSON output); embeddings via voyage or any cheap embedding API — abstract behind `embeddings.py`
- All LLM calls go through a provider-agnostic interface (`extraction/llm.py`); model + provider set in config. Default: Anthropic Haiku via Batch API. Must also support any OpenAI-compatible endpoint (Gemini, Ollama/local) so provider swaps are config-only.
- APScheduler for polling (no Celery/Redis in v1 — keep it one process)
- `httpx` for marketplace APIs/feeds where available
- Pydantic v2 models everywhere; mypy strict
- Email via SMTP (config in env), Jinja2 template for digest

## Repo layout

```
partscout/
  adapters/          # one module per source, all implement SourceAdapter
    base.py          # SourceAdapter ABC: fetch_new() -> list[RawPost]
    nettimoto.py
    blocket.py
    ...
  extraction/
    extractor.py     # LLM call, returns ExtractedListing
    prompts.py       # extraction + verification prompts
    schemas.py       # Pydantic: RawPost, ExtractedListing, Match
  matching/
    normalizer.py    # part numbers, brand aliases, unit/currency
    matcher.py       # tiered matching logic
  db/
    models.py        # SQLAlchemy
    migrations/      # alembic
  digest/
    emailer.py
    templates/
  scheduler.py       # entrypoint: polls adapters on per-source intervals
  config.py          # source registry: url, poll interval, adapter class, enabled flag
tests/
  fixtures/          # saved HTML snapshots per source — scrapers are tested OFFLINE
  test_adapters/
  test_extraction/   # labeled posts (multilingual) with expected JSON
  test_matching/
```

## Data model (core tables)

- `raw_posts(id, source, source_post_id UNIQUE, url, lang_guess, posted_at, scraped_at, raw_text, raw_html, status)`
- `listings(id, raw_post_id FK, kind ENUM(wtb,fs), category TEXT DEFAULT 'vehicle_parts', item_name_en, item_name_original, identifiers TEXT[], attributes JSONB, condition, price_value, price_currency, country, embedding VECTOR(1024), confidence FLOAT)`
  - Design note: the schema is **vertical-agnostic** so the engine can later serve other collectible niches (vintage tools, hi-fi, outboards) without migration. For vehicle parts, `identifiers` holds OEM part numbers and `attributes` holds `{make, model, year_from, year_to}`. Matching tier 1 runs on `identifiers`; tier 2 on `item_name_en` embeddings + category-specific attribute rules defined per category in `matching/rules/`.
- `matches(id, wtb_id FK, fs_id FK, tier ENUM(part_number, fuzzy), score FLOAT, llm_verdict ENUM(match, likely, no), notified_at)`

## Extraction contract

LLM receives raw post text + source metadata, returns strict JSON:

```json
{
  "kind": "wtb | fs | other",
  "vehicle": {"make": "...", "model": "...", "year_from": null, "year_to": null},
  "part": {"name_en": "front fender dust guard", "name_original": "etulokasuojan roiskeläppä", "part_numbers": ["59093-91"]},
  "condition": "used | new | any | unknown",
  "price": {"value": 40, "currency": "EUR"},
  "location_country": "FI",
  "confidence": 0.0
}
```

Rules:
- `kind: other` for chat/discussion posts — drop them.
- Always translate part name to English in `name_en`; keep original verbatim.
- Extract OEM/part numbers aggressively — they are the highest-value match key.
- Never pre-filter posts with keyword regex (Finnish/Estonian compounding breaks it); classify everything in the monitored categories.

## Matching tiers

1. **Tier 1 — part number exact** (after normalization: strip dashes/spaces/case). Auto-match, score 1.0.
2. **Tier 2 — fuzzy**: same make (via alias table: "HD" = "Harley-Davidson" = "Harley"), cosine similarity on `name_en` embedding > 0.80, year ranges overlap or unknown. Top-5 candidates go to LLM verification with both original texts → verdict + reason.
3. WTB matches FS only. Same-source same-thread matches are excluded.
4. Store every verdict including `no` (prevents re-verifying the same pair).

## Source registry — v1 targets

| Source | Country | Side | Method | Status |
|---|---|---|---|---|
| nettimoto.com (parts) | FI | FS | httpx (JSON-LD) | Implemented |
| biker.ee (forum) | EE | WTB | httpx (phpBB) | Implemented |
| tori.fi (vehicle parts) | FI | FS | httpx (embedded JSON + JSON-LD) | Implemented |
| ss.lv (moto) | LV | FS+WTB | httpx (static HTML) | Implemented |
| blocket.se (MC parts) | SE | FS | — | **Blocked**: robots.txt explicitly prohibits crawling without written permission. Do not scrape. |
| finn.no (MC parts) | NO | FS | — | **Blocked**: robots.txt explicitly prohibits crawling without written permission. Do not scrape. |
| sporthoj.com (MC classifieds, incl. Köpes/WTB) | SE | FS+WTB | httpx (static HTML) | Implemented |

Facebook groups: **out of scope** (login wall, ToS, anti-bot). Note as known demand gap.

blocket.se and finn.no are excluded entirely, not deferred — their `robots.txt` carries an explicit anti-crawling notice ("Crawling ... is prohibited unless you have written permission"), not just path-level `Disallow` rules. Treat this the same as Phase 6's Allegro.pl-first approach: only revisit via an official API or written partnership, never by scraping around the notice.

## Operational rules

- Respect robots.txt; per-source rate limit (default 1 req / 5 s, jittered); identifying User-Agent.
- Poll intervals per source in config (default 30 min marketplaces, 2 h forums).
- **Yield monitoring**: track posts/day per source; if a source drops >70% below its 7-day average, flag in digest — layout probably changed.
- Dead-listing detection: re-check FS URLs before notifying a match older than 48 h.
- All LLM calls logged with token counts; daily cost line in digest.

## Testing rules

- Every adapter has ≥2 saved HTML fixtures in `tests/fixtures/<source>/` and parses them offline. Never hit live sites in tests.
- Extraction has a labeled multilingual set (≥5 posts per language incl. FI, SV, LV) in `tests/test_extraction/labeled.jsonl`; CI asserts field-level accuracy.
- Matching has golden pairs (true matches, near-misses that must NOT match — e.g. same part name, incompatible model years).

## Build phases (work ONE phase per session)

**Phase 1 — vertical slice.** db models + migrations, Nettimoto adapter + one forum adapter, extractor, tier-1 matching only, plaintext email digest, scheduler. Definition of done: end-to-end run on fixtures produces a digest.

**Phase 1.5 — backtest (match-density measurement).** Purpose: validate the load-bearing assumption — that real cross-border WTB↔FS matches occur often enough to sustain the product — BEFORE investing in Phases 2+. This is a measurement phase, not a feature phase.

- Add `fetch_history(since: date) -> Iterator[RawPost]` to the forum adapter(s): paginate backwards through forum WTB sections 12–24 months deep. Rate-limited politely (forums are small servers — 1 req / 5–10 s, run overnight). Marketplace adapters do NOT get history (expired listings are gone; only current FS snapshot is used).
- Extract all historical WTBs through the normal pipeline, flagged `historical=true` in `raw_posts`.
- Time-shifted matching: run historical WTBs against the CURRENT FS snapshot from marketplace adapters, using tier-1 + naive name-similarity matching (Phase 2 quality not required — this measures density, not precision; manual-review the candidate matches).
- Output: a one-page metrics report (script, not dashboard): WTB posts/month per forum+language; parts-category distribution; candidate match count; manually-confirmed match count; implied matches-per-tracked-item-per-month.
- Interpretation note: the snapshot backtest UNDERSTATES live match density (one moment of supply vs continuous monitoring) — treat results as a floor.
- **Kill/continue criteria**: continue to Phase 2 if ≥ 10 confirmed matches from 200 historical WTBs; otherwise park the project as portfolio work.

**Phase 2 — match quality.** Normalizer (part numbers, brand aliases, currency), embeddings + pgvector, tier-2 fuzzy + LLM verification, confidence thresholds, golden-pair test suite.

**Phase 3 — sources.** Add Blocket, Finn.no, Tori, SS.lv via adapter pattern. Each adapter: fixture-first (save HTML, write parser against it, then wire live).

**Phase 4 — hardening.** Yield monitoring, dead-listing checks, retry/backoff, dedup across sources (same listing cross-posted), HTML digest template, deploy script (systemd unit on VPS).

**Phase 5 — wishlist web app.** User-facing tracker that converts scraped demand into opt-in demand.

- Backend: FastAPI in the same repo (`web/api/`), same Postgres. Auth: magic-link email (no passwords in v1).
- Frontend: React + Vite + TS + Tailwind + shadcn (`web/ui/`), mobile-first.
- New tables:
  - `users(id, email UNIQUE, created_at, plan ENUM(free, pro), notify_pref ENUM(instant, daily))`
  - `tracked_items(id, user_id FK, ...same fields as listings extraction schema..., max_price_value, max_price_currency, ship_to_country, active BOOL, created_at)`
  - `match_feedback(id, match_id FK, user_id FK, verdict ENUM(bought, right_part_passed, wrong_part), created_at)`
- Matcher treats `tracked_items` as WTB rows with `confidence=1.0` — same tiered pipeline, no special-casing beyond the join.
- Item entry UX: free-text box → run the existing LLM extractor live → show parsed fields for user confirmation/edit. Reuses `extraction/`, structured data without form friction.
- Match feedback buttons on every alert ("bought / right part, passed / wrong part") → labeled eval data for matching quality.
- Free tier: 2 active tracked items, daily digest. Pro: unlimited items, instant alerts. Launch free-only; Stripe later.
- Growth loop: when the scraper matches a *scraped* forum WTB post, reply publicly in-thread with the match + a link to track the part on the site. Never DM or email scraped users (GDPR). Per-language reply templates in `digest/templates/forum_reply/`.

**Phase 6 — DE/AT/PL expansion (post-revenue).** Adds the largest parts supply in Europe; the value proposition here is purely cross-border (these markets have native saved-search alerts).

- **Allegro.pl first** — official REST API with partner program (developer.allegro.pl). Cleanest source in the system; build as an API adapter, not a scraper.
- **OLX.pl** second — moderate-difficulty scrape.
- **Kleinanzeigen.de / Willhaben.at last** — heavy anti-bot; budget for residential proxies and ongoing breakage. Only worth it once revenue covers proxy costs.
- **Demand-driven scraping pattern** for giant sources: do NOT bulk-extract these. When a WTB/tracked item exists, run targeted searches against the big source (search URL templated from the item's `item_name_en` translated to DE/PL + identifiers) and extract only the result pages. New adapter method: `search(query: SearchSpec) -> list[RawPost]` alongside `fetch_new()`. Cuts extraction volume ~95% on large sources; small Nordic sources stay on full-feed polling.
- Query translation: LLM generates 2–3 native-language search-term variants per tracked item (e.g. "front fender dust guard" → "Schutzblech Spritzschutz vorne"), stored on the tracked item, refreshed when the item is edited.

## Conventions

- `# -*- coding: utf-8 -*-` as the first line of every Python script.
- Type hints everywhere; `ruff` + `mypy --strict` must pass.
- No scraping logic in matching/extraction modules; adapters are the only place that knows about HTML.
- Secrets via env only (`ANTHROPIC_API_KEY`, `DATABASE_URL`, `SMTP_*`).
