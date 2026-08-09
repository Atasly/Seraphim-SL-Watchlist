#!/usr/bin/env python3
"""
Consolidate persistent weekend-sale matches across script runs.

The scraper writes a fresh snapshot for each store list (``matches.fresh.json``)
plus the ACCESS SL Facebook-album snapshot (``matches - access*.json``).  This
script merges those into the persistent ``matches*.json`` files that the site
is generated from:

* Each item is one card and is stored exactly once: items are identified by
  ``(store_name, image_url)`` and never re-added once present.
* Existing items are NEVER updated (sale photos are assumed stable); if a store
  changes its photo, the old item is kept and the new one is dropped.
* Items older than ``--keep-days`` (default 4, the Fri/Sat/Sun weekend) expire.
* The ACCESS SL matches are appended to each persistent file and the temporary
  fresh/access files are deleted afterwards.
* Local image copies in docs/img/fb older than ``--keep-days`` are purged.

Usage:
    python consolidate_matches.py --keep-days 4 ^
        --main "matches.json" --fresh "matches.fresh.json" --access "matches - access.json" ^
        --main "matches - fatpack.json" --fresh "matches - fatpack.fresh.json" --access "matches - access - fatpack.json" ^
        --main "matches - build.json" --fresh "matches - build.fresh.json" --access "matches - access - build.json"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).parent
DEFAULT_IMAGES_DIR = ROOT / "docs" / "img" / "fb"


def load_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  ERROR: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def parse_day(matched_at: str) -> Optional[datetime]:
    try:
        return datetime.strptime(matched_at, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def consolidate(
    prev: List[dict], fresh: List[dict], access: List[dict], keep_days: int, now: datetime
) -> List[dict]:
    """Merge fresh + access snapshots into the persistent list.

    - Items already present (same store+image) are kept as-is.
    - Stores already present never get new/updated items (use the old one only).
    - New stores get every one of their items appended.
    - Items older than keep_days expire.
    """
    cutoff = (now - timedelta(days=keep_days)).date()

    for item in prev:
        if not item.get("matched_at"):
            item["matched_at"] = now.strftime("%Y-%m-%d")
        if not item.get("sale_day"):
            item["sale_day"] = ""

    prev_keys = {
        ((item.get("store_name") or "").strip().lower(), item.get("image_url") or "")
        for item in prev
    }
    prev_stores = {(item.get("store_name") or "").strip().lower() for item in prev}

    merged: List[dict] = list(prev)
    seen_keys = set(prev_keys)
    today = now.strftime("%Y-%m-%d")

    for item in list(fresh) + list(access):
        store = (item.get("store_name") or "").strip().lower()
        img = item.get("image_url") or ""
        if not store or not img:
            continue
        key = (store, img)
        if key in seen_keys:
            continue
        if store in prev_stores:
            continue
        seen_keys.add(key)
        if not item.get("matched_at"):
            item["matched_at"] = today
        if not item.get("sale_day"):
            item["sale_day"] = ""
        merged.append(item)

    kept: List[dict] = []
    for item in merged:
        day = parse_day(item.get("matched_at"))
        if day is None:
            day = now
        if day.date() >= cutoff:
            kept.append(item)
    return kept


def cleanup_images(images_dir: Path, keep_days: int) -> None:
    cutoff = time.time() - keep_days * 86400
    removed = 0
    kept = 0
    if not images_dir.exists():
        return
    for path in images_dir.iterdir():
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                kept += 1
        else:
            kept += 1
    print(f"  images: {removed} removed, {kept} kept ({keep_days}-day cutoff)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--main",
        action="append",
        required=True,
        metavar="PATH",
        help="Persistent output matches file. Repeat for each store list.",
    )
    parser.add_argument(
        "--fresh",
        action="append",
        required=True,
        metavar="PATH",
        help="Fresh scraper snapshot to merge in (same order as --main).",
    )
    parser.add_argument(
        "--access",
        action="append",
        metavar="PATH",
        help="ACCESS SL snapshot to append (same order as --main; optional).",
    )
    parser.add_argument("--keep-days", type=int, default=4)
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="Base directory for all relative file paths (default: script folder).",
    )
    parser.add_argument(
        "--images-dir", default=str(DEFAULT_IMAGES_DIR), help="docs/img/fb folder."
    )
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    images_dir = Path(args.images_dir)
    if not images_dir.is_absolute():
        images_dir = root / images_dir

    if len(args.fresh) != len(args.main):
        print("ERROR: --fresh must repeat the same number of times as --main", file=sys.stderr)
        sys.exit(1)
    access = args.access or [None] * len(args.main)
    if len(access) < len(args.main):
        access = access + [None] * (len(args.main) - len(access))

    now = datetime.now()
    for idx, main_name in enumerate(args.main):
        main_path = root / main_name
        fresh_path = root / args.fresh[idx]
        access_name = access[idx]
        access_path = root / access_name if access_name else None

        prev = load_json(main_path)
        fresh = load_json(fresh_path)
        access_items = load_json(access_path) if access_path else []
        before = len(prev)
        prev_ids = {id(item) for item in prev}

        merged = consolidate(prev, fresh, access_items, args.keep_days, now)

        kept_prev = sum(1 for item in merged if id(item) in prev_ids)
        expired = before - kept_prev
        added = len(merged) - kept_prev

        main_path.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            f"  {main_name}: {before} -> {len(merged)} "
            f"({added} new, {expired} expired)"
        )

        for temp_path in (fresh_path, access_path):
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    if not args.no_cleanup:
        cleanup_images(images_dir, args.keep_days)


if __name__ == "__main__":
    main()
