#!/usr/bin/env python3
"""Inspect Android bitmap dimensions, mode, and alpha bounds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def expand_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value)
        if any(char in value for char in "*?["):
            paths.extend(sorted(path.parent.glob(path.name)))
        else:
            paths.append(path)
    return paths


def inspect(path: Path) -> dict:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        alpha_bbox = rgba.getchannel("A").getbbox()
        return {
            "path": str(path),
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "format": image.format,
            "alpha_bbox": alpha_bbox,
            "has_alpha": "A" in image.getbands(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print dimensions and alpha bounds for Android bitmap assets."
    )
    parser.add_argument("paths", nargs="+", help="Files or simple glob patterns.")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    files = expand_paths(args.paths)
    if not files:
        raise SystemExit("No matching files")
    results = [inspect(path) for path in files]
    print(json.dumps(results, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
