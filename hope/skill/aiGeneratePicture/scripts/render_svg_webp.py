#!/usr/bin/env python3
"""Rasterize manifest-listed SVG assets to transparent, lossless WebP files."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WINDOWS_BROWSERS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


def find_browser(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        raise RuntimeError(f"Browser executable not found: {candidate}")
    for candidate in WINDOWS_BROWSERS:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "No Chromium-compatible browser found. Pass --browser with Edge or Chrome."
    )


def read_manifest(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Manifest must contain a non-empty assets array")
    checked: list[dict] = []
    for item in assets:
        if not isinstance(item, dict):
            raise ValueError("Each manifest asset must be an object")
        for key in ("name", "svg", "width", "height"):
            if key not in item:
                raise ValueError(f"Manifest asset is missing {key!r}")
        width = int(item["width"])
        height = int(item["height"])
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid target size for {item['name']}: {width}x{height}")
        checked.append(
            {
                "name": str(item["name"]),
                "svg": str(item["svg"]),
                "width": width,
                "height": height,
                "webp": str(item.get("webp") or f"webp/{item['name']}.webp"),
            }
        )
    return checked


def render_svg(
    browser: Path,
    svg_path: Path,
    png_path: Path,
    width: int,
    height: int,
    work_dir: Path,
) -> Image.Image:
    if not svg_path.exists():
        raise FileNotFoundError(svg_path)
    html_path = work_dir / f"{svg_path.stem}.html"
    html_path.write_text(
        """<!doctype html>
<meta charset="utf-8">
<style>
html, body { margin: 0; padding: 0; overflow: hidden; background: transparent; }
img { display: block; width: %dpx; height: %dpx; }
</style>
<img src="%s" width="%d" height="%d">
"""
        % (width, height, html.escape(svg_path.resolve().as_uri()), width, height),
        encoding="utf-8",
    )
    profile_dir = work_dir / f"profile-{svg_path.stem}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--default-background-color=00000000",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=500",
        f"--user-data-dir={profile_dir}",
        f"--window-size={width},{height}",
        f"--screenshot={png_path}",
        html_path.resolve().as_uri(),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"SVG render failed for {svg_path.name}: {detail[-1000:]}")
    image = Image.open(png_path).convert("RGBA")
    if image.size != (width, height):
        if image.width < width or image.height < height:
            raise RuntimeError(
                f"Unexpected screenshot size for {svg_path.name}: {image.size}, "
                f"expected at least {width}x{height}"
            )
        image = image.crop((0, 0, width, height))
    return image


def save_webp(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "WEBP", lossless=True, quality=100, method=6)


def make_contact_sheet(records: list[dict], output_root: Path) -> Path:
    columns = 4
    tile_width, tile_height = 190, 156
    rows = (len(records) + columns - 1) // columns
    sheet = Image.new(
        "RGBA",
        (columns * tile_width + 24, rows * tile_height + 48),
        "#F3F6F8",
    )
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 11)
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
        title_font = font
    draw.text((16, 14), "SVG to WebP preview", fill="#20324A", font=title_font)
    for index, record in enumerate(records):
        col = index % columns
        row = index // columns
        x = 12 + col * tile_width
        y = 42 + row * tile_height
        draw.rounded_rectangle(
            (x, y, x + tile_width - 10, y + tile_height - 10),
            radius=10,
            fill="#FFFFFF",
        )
        image = Image.open(output_root / record["webp"]).convert("RGBA")
        image.thumbnail((116, 116), Image.Resampling.LANCZOS)
        tile_x = x + (tile_width - 10 - image.width) // 2
        sheet.alpha_composite(image, (tile_x, y + 5))
        draw.text((x + 8, y + 123), record["name"][:28], fill="#20324A", font=font)
    output = output_root / "contact-sheet.webp"
    sheet.save(output, "WEBP", lossless=True, quality=100, method=6)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render SVG files from a JSON asset manifest to WebP."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Directory for WebP output; defaults to the manifest directory.",
    )
    parser.add_argument("--browser", help="Edge or Chrome executable path.")
    parser.add_argument(
        "--only",
        action="append",
        dest="only",
        help="Render only this asset name; repeat for multiple names.",
    )
    parser.add_argument(
        "--contact-sheet",
        action="store_true",
        help="Create contact-sheet.webp after rendering.",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    source_root = manifest_path.parent
    output_root = (args.output_root or source_root).resolve()
    records = read_manifest(manifest_path)
    if args.only:
        selected = set(args.only)
        records = [record for record in records if record["name"] in selected]
        missing = selected - {record["name"] for record in records}
        if missing:
            raise ValueError(f"Names not found in manifest: {', '.join(sorted(missing))}")
    browser = find_browser(args.browser)
    output_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="svg-webp-render-") as temp_name:
        work_dir = Path(temp_name)
        for record in records:
            svg_path = Path(record["svg"])
            if not svg_path.is_absolute():
                svg_path = source_root / svg_path
            png_path = work_dir / f"{record['name']}.png"
            image = render_svg(
                browser,
                svg_path,
                png_path,
                record["width"],
                record["height"],
                work_dir,
            )
            save_webp(image, output_root / record["webp"])
            print(
                f"{record['name']}: {record['width']}x{record['height']} -> "
                f"{output_root / record['webp']}"
            )

    if args.contact_sheet:
        print(f"contact sheet: {make_contact_sheet(records, output_root)}")
    print(f"rendered {len(records)} asset(s) with {browser}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
