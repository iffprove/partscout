# -*- coding: utf-8 -*-
"""Run the full Phase 1 pipeline on saved fixtures and print extracted JSON.

Usage:
    uv run python scripts/run_pipeline.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if not api_key or api_key.startswith("sk-ant-..."):
    sys.exit(
        "ERROR: Set a real ANTHROPIC_API_KEY in .env before running this script."
    )

# --- project root on path ---
sys.path.insert(0, str(Path(__file__).parent.parent))

from partscout.adapters.biker_ee import BikerEeAdapter
from partscout.adapters.nettimoto import NettimotoAdapter
from partscout.extraction.extractor import Extractor
from partscout.extraction.llm import build_client
from partscout.extraction.schemas import ExtractedListing, RawPost

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
SAMPLES_FILE = Path(__file__).parent.parent / "tests" / "extraction_samples.txt"

_netti = NettimotoAdapter(config=None)
_biker = BikerEeAdapter(config=None)


def _json(listing: ExtractedListing) -> str:
    return json.dumps(listing.model_dump(), ensure_ascii=False, indent=2)


def _header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("=" * 60)


def run_fixtures(extractor: Extractor) -> None:
    # ---- Nettimoto HTML fixtures ----
    for html_path in sorted((FIXTURES / "nettimoto").glob("*.html")):
        _header(f"NETTIMOTO: {html_path.stem[:55]}")
        url = f"https://www.nettivaraosa.com/en/moottoripyoran-varaosat-ja-tarvikkeet/0"
        post = _netti._parse_listing_page(html_path.read_text(encoding="utf-8"), url)
        if post is None:
            print("  [parse failed]")
            continue
        print(f"  raw_text: {post.raw_text[:120]}")
        result = extractor.extract(post, country_hint="FI")
        if result is None:
            print("  [extraction failed]")
        else:
            print(_json(result))

    # ---- Biker.ee forum fixtures ----
    for html_path in sorted((FIXTURES / "forum").glob("*.html")):
        _header(f"FORUM: {html_path.stem[:55]}")
        url = f"https://biker.ee/phpbb/viewtopic.php?f=90&t=0"
        post = _biker._parse_topic_page(html_path.read_text(encoding="utf-8"), url)
        if post is None:
            print("  [skipped — no buy/sell prefix or no postbody]")
            continue
        print(f"  raw_text: {post.raw_text[:120]}")
        result = extractor.extract(post, country_hint="EE")
        if result is None:
            print("  [extraction failed]")
        else:
            print(_json(result))


def run_text_samples(extractor: Extractor) -> None:
    """Parse extraction_samples.txt and extract each sample."""
    raw = SAMPLES_FILE.read_text(encoding="utf-8")

    # Split on --- source, LANG --- headers
    blocks = re.split(r"\n(?=---)", raw.strip())
    posts: list[tuple[str, str, str]] = []  # (source, lang, text)
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue
        header_match = re.match(r"---\s*(.+?),\s*(\w+)\s*---", lines[0])
        if not header_match:
            continue
        source = header_match.group(1).strip()
        lang = header_match.group(2).strip().lower()
        text = "\n".join(lines[1:]).strip()
        if text:
            posts.append((source, lang, text))

    _header(f"TEXT SAMPLES ({len(posts)} posts from extraction_samples.txt)")

    for i, (source, lang, text) in enumerate(posts, 1):
        print(f"\n--- [{i}/{len(posts)}] {source} ({lang.upper()}) ---")
        print(f"  input: {text[:100]}")
        post = RawPost(
            source=source.lower().replace(" ", "_").replace(".", "_"),
            source_post_id=f"sample-{i}",
            url=f"http://{source}/sample/{i}",
            lang_guess=lang,
            raw_text=text,
        )
        country_hint = {
            "fi": "FI", "et": "EE", "lv": "LV", "sv": "SE", "en": "",
        }.get(lang, "")
        result = extractor.extract(post, country_hint=country_hint)
        if result is None:
            print("  [extraction failed]")
        else:
            print(_json(result))


def main() -> None:
    client = build_client(
        provider="anthropic",
        model=os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001"),
        api_key=api_key,
    )
    extractor = Extractor(client)

    print(f"Model: {os.environ.get('LLM_MODEL', 'claude-haiku-4-5-20251001')}")
    print(f"Running on {len(list((FIXTURES/'nettimoto').glob('*.html')))} nettimoto fixtures,")
    print(f"           {len(list((FIXTURES/'forum').glob('*.html')))} forum fixtures,")
    print(f"           text samples from extraction_samples.txt")

    run_fixtures(extractor)
    run_text_samples(extractor)

    print("\n\nDone.")


if __name__ == "__main__":
    main()
