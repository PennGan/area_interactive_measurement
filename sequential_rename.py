#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rename files or directories in ascending name order to "
            "'<prefix><number>'."
        )
    )
    parser.add_argument("target", help="Target directory whose contents will be renamed.")
    parser.add_argument("prefix", help="Prefix for the new names.")
    parser.add_argument("start", type=int, help="Starting number.")
    parser.add_argument(
        "--type",
        choices=("files", "dirs", "all"),
        default="files",
        help="Rename only files, only directories, or all entries. Default: files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the rename plan without changing anything.",
    )
    return parser.parse_args()


def should_include(path: Path, entry_type: str) -> bool:
    if entry_type == "files":
        return path.is_file()
    if entry_type == "dirs":
        return path.is_dir()
    return path.is_file() or path.is_dir()


def build_plan(entries: list[Path], prefix: str, start: int) -> list[tuple[Path, str]]:
    plan: list[tuple[Path, str]] = []
    for index, path in enumerate(entries, start=start):
        if path.is_file():
            new_name = f"{prefix}{index}{path.suffix}"
        else:
            new_name = f"{prefix}{index}"
        plan.append((path, new_name))
    return plan


def validate_plan(plan: list[tuple[Path, str]]) -> None:
    seen: set[str] = set()
    for _, new_name in plan:
        if new_name in seen:
            raise ValueError(f"Duplicate target name generated: {new_name}")
        seen.add(new_name)


def apply_plan(plan: list[tuple[Path, str]], dry_run: bool) -> None:
    if dry_run:
        for old_path, new_name in plan:
            print(f"{old_path.name} -> {new_name}")
        return

    temp_moves: list[tuple[Path, Path]] = []
    final_moves: list[tuple[Path, Path, str]] = []

    for old_path, new_name in plan:
        temp_path = old_path.with_name(f".rename_tmp_{uuid.uuid4().hex}_{old_path.name}")
        temp_moves.append((old_path, temp_path))
        final_moves.append((temp_path, old_path.with_name(new_name), old_path.name))

    for source, temp_path in temp_moves:
        os.replace(source, temp_path)

    for temp_path, final_path, old_name in final_moves:
        os.replace(temp_path, final_path)
        print(f"{old_name} -> {final_path.name}")


def main() -> int:
    args = parse_args()
    target_dir = Path(args.target).expanduser().resolve()

    if not target_dir.exists():
        print(f"Target directory does not exist: {target_dir}", file=sys.stderr)
        return 1
    if not target_dir.is_dir():
        print(f"Target path is not a directory: {target_dir}", file=sys.stderr)
        return 1

    entries = sorted(
        (
            path
            for path in target_dir.iterdir()
            if should_include(path, args.type)
        ),
        key=lambda path: path.name,
    )

    if not entries:
        print("No matching entries found.", file=sys.stderr)
        return 1

    try:
        plan = build_plan(entries, args.prefix, args.start)
        validate_plan(plan)
        apply_plan(plan, args.dry_run)
    except Exception as exc:
        print(f"Rename failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
