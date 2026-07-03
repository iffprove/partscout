# -*- coding: utf-8 -*-
"""Phase 1.5 backtest: measure cross-border WTB<->FS match density.

Two steps:

  1. `run`    — fetch historical WTB posts (biker.ee paginated back to --since;
                ss.lv's shallow archive, which can't be date-filtered), fetch
                the current FS snapshot (nettimoto, tori.fi, ss.lv), extract
                both through the normal LLM pipeline, run tier-1 exact + naive
                name-similarity matching, write candidates.csv for manual
                review + summary.json.
  2. `report` — after you've filled in the `confirmed` column in candidates.csv
                (y/n), tally results against the kill/continue threshold.

Usage:
    uv run python scripts/backtest.py run --since 2024-07-01
    # ... manually mark candidates.csv `confirmed` column y/n ...
    uv run python scripts/backtest.py report
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from partscout.adapters.biker_ee import BikerEeAdapter  # noqa: E402
from partscout.adapters.nettimoto import NettimotoAdapter  # noqa: E402
from partscout.adapters.ss_lv import SsLvAdapter  # noqa: E402
from partscout.adapters.tori import ToriAdapter  # noqa: E402
from partscout.extraction.extractor import Extractor  # noqa: E402
from partscout.extraction.llm import build_client  # noqa: E402
from partscout.extraction.schemas import ExtractedListing, RawPost  # noqa: E402
from partscout.matching.normalizer import (  # noqa: E402
    brands_compatible,
    normalize_identifiers,
    years_overlap,
)

DEFAULT_OUT_DIR = Path(__file__).parent / "backtest_output"
NAME_SIMILARITY_THRESHOLD = 0.5

# Kill/continue criteria decided in CLAUDE.md Phase 1.5: continue to Phase 2 if
# >= 10 confirmed matches out of 200 historical WTBs (5%); otherwise park the project.
KILL_THRESHOLD_CONFIRMED = 10
KILL_THRESHOLD_WTB_COUNT = 200


@dataclass
class Listing:
    raw: RawPost
    extracted: ExtractedListing


@dataclass
class Candidate:
    tier: str  # "part_number" | "name_similarity"
    score: float
    wtb: Listing
    fs: Listing


def _build_extractor() -> Extractor:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-..."):
        sys.exit("ERROR: Set a real ANTHROPIC_API_KEY in .env before running this script.")
    client = build_client(
        provider=os.environ.get("LLM_PROVIDER", "anthropic"),
        model=os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001"),
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL"),
    )
    return Extractor(client)


def _extract_source(
    extractor: Extractor, source_name: str, posts: list[RawPost], country_hint: str
) -> list[Listing]:
    """Extract every post from one source, keeping both wtb and fs kinds.

    Kind is decided by the LLM per post, not by which adapter/endpoint the
    post came from — e.g. ss.lv mixes FS and WTB in the same category.
    """
    out: list[Listing] = []
    dropped = 0
    for post in posts:
        result = extractor.extract(post, country_hint=country_hint)
        if result is None or result.kind == "other":
            dropped += 1
            continue
        out.append(Listing(raw=post, extracted=result))
    wtb_count = sum(1 for listing in out if listing.extracted.kind == "wtb")
    fs_count = sum(1 for listing in out if listing.extracted.kind == "fs")
    print(
        f"  {source_name}: extracted {wtb_count} wtb + {fs_count} fs "
        f"({dropped} dropped/other)"
    )
    return out


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _find_candidates(wtbs: list[Listing], fss: list[Listing]) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen_pairs: set[tuple[str, str]] = set()

    fs_ids_by_post: dict[str, set[str]] = {
        fs.raw.source_post_id: normalize_identifiers(fs.extracted.part.part_numbers)
        for fs in fss
    }

    for wtb in wtbs:
        wtb_ids = normalize_identifiers(wtb.extracted.part.part_numbers)
        if not wtb_ids:
            continue
        for fs in fss:
            fs_ids = fs_ids_by_post[fs.raw.source_post_id]
            if fs_ids and (wtb_ids & fs_ids):
                pair_key = (wtb.raw.source_post_id, fs.raw.source_post_id)
                candidates.append(Candidate(tier="part_number", score=1.0, wtb=wtb, fs=fs))
                seen_pairs.add(pair_key)

    for wtb in wtbs:
        for fs in fss:
            pair_key = (wtb.raw.source_post_id, fs.raw.source_post_id)
            if pair_key in seen_pairs:
                continue
            if not brands_compatible(wtb.extracted.vehicle.make, fs.extracted.vehicle.make):
                continue
            if not years_overlap(
                wtb.extracted.vehicle.year_from,
                wtb.extracted.vehicle.year_to,
                fs.extracted.vehicle.year_from,
                fs.extracted.vehicle.year_to,
            ):
                continue
            sim = _name_similarity(wtb.extracted.part.name_en, fs.extracted.part.name_en)
            if sim >= NAME_SIMILARITY_THRESHOLD:
                candidates.append(Candidate(tier="name_similarity", score=sim, wtb=wtb, fs=fs))
                seen_pairs.add(pair_key)

    return candidates


def _month_key(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m") if dt else "unknown"


def cmd_run(args: argparse.Namespace) -> None:
    since: date = datetime.strptime(args.since, "%Y-%m-%d").date()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    extractor = _build_extractor()

    print(f"Fetching historical WTB posts back to {since} (this can take hours)...")
    biker = BikerEeAdapter(config=None)
    biker_history = list(biker.fetch_history(since=since))
    print(f"  biker.ee: fetched {len(biker_history)} historical raw posts")

    ss_lv_history_adapter = SsLvAdapter(config=None)
    ss_lv_history = list(ss_lv_history_adapter.fetch_history(since=since))
    print(f"  ss.lv: fetched {len(ss_lv_history)} historical raw posts (archive, not date-bounded)")

    print("Fetching current snapshots from nettimoto, tori.fi, ss.lv...")
    netti_posts = NettimotoAdapter(config=None).fetch_new()
    print(f"  nettimoto: fetched {len(netti_posts)} raw posts")
    tori_posts = ToriAdapter(config=None).fetch_new()
    print(f"  tori: fetched {len(tori_posts)} raw posts")
    ss_lv_posts = SsLvAdapter(config=None).fetch_new()
    print(f"  ss.lv: fetched {len(ss_lv_posts)} raw posts")

    print("Extracting...")
    historical_listings = _extract_source(
        extractor, "biker.ee (historical)", biker_history, country_hint="EE"
    ) + _extract_source(
        extractor, "ss.lv (historical)", ss_lv_history, country_hint="LV"
    )
    current_listings = (
        _extract_source(extractor, "nettimoto (current)", netti_posts, country_hint="FI")
        + _extract_source(extractor, "tori (current)", tori_posts, country_hint="FI")
        + _extract_source(extractor, "ss.lv (current)", ss_lv_posts, country_hint="LV")
    )

    # WTB demand pool: historical WTBs (expired, but were real demand) plus any
    # currently-live WTB posts (e.g. from ss.lv, which mixes WTB into its
    # current snapshot) — both are valid signal for the density measurement.
    # FS supply pool: current listings only — an expired historical FS post
    # isn't available to match against.
    wtbs = [listing for listing in historical_listings if listing.extracted.kind == "wtb"]
    wtbs += [listing for listing in current_listings if listing.extracted.kind == "wtb"]
    fss = [listing for listing in current_listings if listing.extracted.kind == "fs"]
    print(f"  total: {len(wtbs)} wtb listings, {len(fss)} fs listings")

    history_posts = biker_history + ss_lv_history

    print("Running tier-1 exact + naive name-similarity matching...")
    candidates = _find_candidates(wtbs, fss)
    print(f"  {len(candidates)} candidate matches found")

    candidates_path = out_dir / "candidates.csv"
    with candidates_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "tier",
                "score",
                "wtb_url",
                "wtb_part_en",
                "wtb_text",
                "fs_url",
                "fs_part_en",
                "fs_text",
                "confirmed",  # fill in y/n by hand
            ]
        )
        for c in candidates:
            writer.writerow(
                [
                    c.tier,
                    f"{c.score:.3f}",
                    c.wtb.raw.url,
                    c.wtb.extracted.part.name_en,
                    c.wtb.raw.raw_text[:300],
                    c.fs.raw.url,
                    c.fs.extracted.part.name_en,
                    c.fs.raw.raw_text[:300],
                    "",
                ]
            )

    posts_by_month: Counter[str] = Counter(_month_key(p.posted_at) for p in history_posts)
    wtb_by_make: Counter[str] = Counter(w.extracted.vehicle.make or "unknown" for w in wtbs)

    summary = {
        "since": args.since,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "historical_raw_posts": len(history_posts),
        # historical WTBs (biker.ee + ss.lv archive) plus any currently-live
        # WTB posts (e.g. from ss.lv's current snapshot) — the full demand pool.
        "wtb_demand_listings": len(wtbs),
        "fs_snapshot_listings": len(fss),
        "candidate_match_count": len(candidates),
        "wtb_posts_by_month": dict(sorted(posts_by_month.items())),
        "wtb_by_vehicle_make": dict(wtb_by_make.most_common()),
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nWrote {candidates_path} and {summary_path}")
    print(f"\n{len(candidates)} candidates need manual review — open candidates.csv,")
    print("fill in the 'confirmed' column with y/n for each row, then run:")
    print(f"  uv run python scripts/backtest.py report --out {out_dir}")


def cmd_report(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    candidates_path = out_dir / "candidates.csv"
    summary_path = out_dir / "summary.json"

    if not candidates_path.exists() or not summary_path.exists():
        sys.exit(f"ERROR: {candidates_path} or {summary_path} not found — run `run` first.")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    with candidates_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    confirmed = sum(
        1 for r in rows if r.get("confirmed", "").strip().lower() in ("y", "yes", "true")
    )
    reviewed = sum(1 for r in rows if r.get("confirmed", "").strip())
    total_wtb = summary["wtb_demand_listings"]

    print("=" * 60)
    print("  PartScout Phase 1.5 backtest report")
    print("=" * 60)
    print(f"Since:                    {summary['since']}")
    print(f"Historical raw posts:     {summary['historical_raw_posts']}")
    print(f"WTB demand listings:      {total_wtb}")
    print(f"Current FS snapshot:      {summary['fs_snapshot_listings']}")
    print(f"Candidate matches:        {summary['candidate_match_count']}")
    print(f"Candidates reviewed:      {reviewed}/{len(rows)}")
    print(f"Confirmed matches:        {confirmed}")

    print("\nWTB posts/month:")
    for month, count in summary["wtb_posts_by_month"].items():
        print(f"  {month}: {count}")

    print("\nWTB by vehicle make:")
    for make, count in summary["wtb_by_vehicle_make"].items():
        print(f"  {make}: {count}")

    if total_wtb > 0:
        implied_monthly = confirmed / total_wtb * 30  # rough: matches per WTB per month-equivalent
        print(f"\nImplied matches per tracked item per month (rough): {implied_monthly:.3f}")

    print("\n--- Kill/continue decision ---")
    print(
        f"Threshold: >= {KILL_THRESHOLD_CONFIRMED} confirmed matches "
        f"from {KILL_THRESHOLD_WTB_COUNT} historical WTBs "
        f"({KILL_THRESHOLD_CONFIRMED / KILL_THRESHOLD_WTB_COUNT:.1%} rate)"
    )
    if total_wtb == 0:
        print("No WTB demand listings — cannot evaluate.")
        return
    if reviewed < len(rows):
        print(f"WARNING: {len(rows) - reviewed} candidates not yet reviewed — decision may change.")

    threshold_rate = KILL_THRESHOLD_CONFIRMED / KILL_THRESHOLD_WTB_COUNT
    actual_rate = confirmed / total_wtb
    print(
        f"Actual: {confirmed} confirmed from {total_wtb} WTB demand listings "
        f"({actual_rate:.1%} rate)"
    )
    if actual_rate >= threshold_rate:
        print("=> CONTINUE to Phase 2.")
    else:
        print("=> Below threshold — park the project as portfolio work "
              "(remember the backtest UNDERSTATES live density; treat as a floor).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Fetch, extract, and match historical vs. current data")
    p_run.add_argument("--since", required=True, help="YYYY-MM-DD, how far back to backtest")
    p_run.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="Output directory")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser(
        "report", help="Tally a reviewed candidates.csv against the threshold"
    )
    p_report.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="Output directory")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
