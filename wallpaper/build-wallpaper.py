#!/usr/bin/env python3
"""Render studio-grade dual-display macOS desktop keybind cheat-sheet wallpapers.

Single source of truth:
- Reads live keybind structure directly from `herdr/cheatsheet.py` (which parses `herdr/config.toml`)
- Renders crisp vector typography (Maple Mono NF CN) via SVG -> rsvg-convert -> ImageMagick composite
- Outputs native wallpapers for:
    1) External 5K main display: 4608x2592 (16:9)
    2) Built-in MacBook Retina:  3024x1964 (3:2, with extra top margin for notch)
"""

from __future__ import annotations

import html
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WALLPAPER_DIR = Path(__file__).resolve().parent
DOTFILES_DIR = WALLPAPER_DIR.parent
CHEATSHEET_PATH = DOTFILES_DIR / "herdr" / "cheatsheet.py"
DEFAULT_CONFIG_PATH = DOTFILES_DIR / "herdr" / "config.toml"
OUT_DIR = WALLPAPER_DIR / "out"

# Display targets: (filename, width, height, top_safe_ratio, bottom_safe_ratio, card_left_ratio)
TARGETS = [
    ("herdr-cheatsheet-5k-16x9.png", 4608, 2592, 0.065, 0.095, 0.365),
    ("herdr-cheatsheet-macbook-3x2.png", 3024, 1964, 0.080, 0.100, 0.295),
]

FONT_FAMILY = "Maple Mono NF CN"


def load_cheatsheet_module():
    spec = importlib.util.spec_from_file_location("herdr_cheatsheet", CHEATSHEET_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {CHEATSHEET_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_base_image() -> Path:
    for name in ("base-bg.jpg", "base-bg.png", "base-bg.webp"):
        p = WALLPAPER_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError(f"Base artwork not found in {WALLPAPER_DIR} (expected base-bg.jpg or base-bg.png)")


def estimate_key_pill_width(text: str, font_size: float) -> float:
    w = 0.0
    for ch in text:
        w += 1.05 if ord(ch) > 127 else 0.62
    return w * font_size + font_size * 1.15


def build_svg(data: dict[str, Any], width: int, height: int, top_r: float, bot_r: float, left_r: float) -> str:
    s = height / 2592.0

    margin_right = int(width * 0.036)
    card_x = int(width * left_r)
    card_y = int(height * top_r)
    card_w = width - card_x - margin_right
    card_h = height - card_y - int(height * bot_r)

    pad_x = int(66 * s)
    pad_top = int(58 * s)
    pad_bot = int(46 * s)
    radius = int(34 * s)

    secs = {sec["id"]: sec for sec in data["sections"]}

    left_sections = [secs["panes"], secs["tabs"]]
    right_sections = [secs["agents"], secs["prefix"]]

    col_gap = int(58 * s)
    inner_w = card_w - pad_x * 2
    col_w = (inner_w - col_gap) / 2.0

    header_h = int(124 * s)
    footer_h = int(86 * s)
    body_top = card_y + pad_top + header_h
    body_h = card_h - pad_top - pad_bot - header_h - footer_h

    max_items_per_col = max(
        sum(len(sec["items"]) for sec in left_sections),
        sum(len(sec["items"]) for sec in right_sections),
    )
    sec_hdr_h = int(60 * s)
    sec_gap = int(46 * s)
    avail_for_rows = body_h - sec_hdr_h * 2 - sec_gap
    row_h = min(int(98 * s), max(int(64 * s), avail_for_rows / max(max_items_per_col, 1)))

    title_fs = int(44 * s)
    subtitle_fs = int(22 * s)
    sec_fs = int(30 * s)
    key_fs = int(26 * s)
    label_fs = int(27 * s)
    footer_fs = int(24 * s)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "  <defs>",
        '    <linearGradient id="cardBg" x1="0%" y1="0%" x2="100%" y2="100%">',
        '      <stop offset="0%" stop-color="#1b1d2e" stop-opacity="0.86"/>',
        '      <stop offset="100%" stop-color="#24273a" stop-opacity="0.80"/>',
        "    </linearGradient>",
        '    <linearGradient id="topAccent" x1="0%" y1="0%" x2="100%" y2="0%">',
        '      <stop offset="0%" stop-color="#18ecff" stop-opacity="0.95"/>',
        '      <stop offset="55%" stop-color="#eed49f" stop-opacity="0.75"/>',
        '      <stop offset="100%" stop-color="#c6a0f6" stop-opacity="0.45"/>',
        "    </linearGradient>",
        '    <filter id="cardShadow" x="-8%" y="-8%" width="116%" height="116%">',
        f'      <feDropShadow dx="0" dy="{int(20*s)}" stdDeviation="{int(28*s)}" flood-color="#0b0c14" flood-opacity="0.55"/>',
        "    </filter>",
        "  </defs>",
        "",
        "  <!-- Main frosted glass card -->",
        f'  <rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="{radius}" '
        f'fill="url(#cardBg)" stroke="#494d64" stroke-opacity="0.65" stroke-width="{max(2, int(2.2*s))}" filter="url(#cardShadow)"/>',
        f'  <rect x="{card_x + radius}" y="{card_y}" width="{card_w - radius * 2}" height="{max(3, int(4*s))}" rx="{max(2, int(2*s))}" fill="url(#topAccent)"/>',
        "",
        "  <!-- Header -->",
        f'  <text x="{card_x + pad_x}" y="{card_y + pad_top + int(42*s)}" '
        f'font-family="{FONT_FAMILY}" font-size="{title_fs}" font-weight="700" fill="#cad3f5">'
        f'HERDR <tspan fill="#18ecff">·</tspan> DWM + VIM KEYMAP</text>',
        f'  <text x="{card_x + pad_x}" y="{card_y + pad_top + int(84*s)}" '
        f'font-family="{FONT_FAMILY}" font-size="{subtitle_fs}" font-weight="400" fill="#8087a2">'
        f'Leaderless 3-Layer Keymap · Auto-synced from ~/.config/herdr/config.toml</text>',
        f'  <text x="{card_x + card_w - pad_x}" y="{card_y + pad_top + int(42*s)}" text-anchor="end" '
        f'font-family="{FONT_FAMILY}" font-size="{subtitle_fs}" font-weight="600" fill="#eed49f">'
        f'MOStudio-AI · Cmd+/ Popup</text>',
        f'  <line x1="{card_x + pad_x}" y1="{card_y + pad_top + int(106*s)}" '
        f'x2="{card_x + card_w - pad_x}" y2="{card_y + pad_top + int(106*s)}" '
        f'stroke="#363a4f" stroke-width="{max(1, int(2*s))}"/>',
        "",
        "  <!-- Vertical divider between columns -->",
        f'  <line x1="{card_x + pad_x + col_w + col_gap/2:.1f}" y1="{body_top}" '
        f'x2="{card_x + pad_x + col_w + col_gap/2:.1f}" y2="{card_y + card_h - pad_bot - footer_h - int(12*s)}" '
        f'stroke="#363a4f" stroke-opacity="0.7" stroke-width="{max(1, int(1.5*s))}"/>',
    ]

    def render_column(col_sections: list[dict[str, Any]], col_x: float) -> None:
        y = float(body_top)
        pill_h = int(48 * s)
        pill_r = int(11 * s)
        key_zone_w = col_w * 0.455

        for idx, sec in enumerate(col_sections):
            if idx > 0:
                y += sec_gap
            color = sec["color"]
            title_esc = html.escape(sec["title"])
            badge_esc = html.escape(sec["badge"])

            parts.append(
                f'  <circle cx="{col_x + int(9*s):.1f}" cy="{y + int(22*s):.1f}" r="{int(6.5*s):.1f}" fill="{color}"/>'
            )
            parts.append(
                f'  <text x="{col_x + int(28*s):.1f}" y="{y + int(32*s):.1f}" '
                f'font-family="{FONT_FAMILY}" font-size="{sec_fs}" font-weight="700" fill="{color}">{title_esc}</text>'
            )
            parts.append(
                f'  <text x="{col_x + col_w:.1f}" y="{y + int(30*s):.1f}" text-anchor="end" '
                f'font-family="{FONT_FAMILY}" font-size="{int(20*s)}" font-weight="500" fill="#6e738d">{badge_esc}</text>'
            )
            y += sec_hdr_h

            for row_i, it in enumerate(sec["items"]):
                row_mid = y + row_h * 0.50
                key_text = it["key"]
                pill_w = min(key_zone_w - int(18 * s), estimate_key_pill_width(key_text, key_fs))
                pill_y = row_mid - pill_h / 2.0

                if row_i % 2 == 1:
                    parts.append(
                        f'  <rect x="{col_x - int(10*s):.1f}" y="{y + int(4*s):.1f}" width="{col_w + int(20*s):.1f}" '
                        f'height="{row_h - int(8*s):.1f}" rx="{int(10*s)}" fill="#363a4f" fill-opacity="0.22"/>'
                    )

                parts.append(
                    f'  <rect x="{col_x:.1f}" y="{pill_y:.1f}" width="{pill_w:.1f}" height="{pill_h}" rx="{pill_r}" '
                    f'fill="#2b2f45" stroke="{color}" stroke-opacity="0.42" stroke-width="{max(1, int(1.6*s))}"/>'
                )
                parts.append(
                    f'  <text x="{col_x + pill_w/2.0:.1f}" y="{row_mid + key_fs*0.35:.1f}" text-anchor="middle" '
                    f'font-family="{FONT_FAMILY}" font-size="{key_fs}" font-weight="600" fill="{color}">'
                    f'{html.escape(key_text)}</text>'
                )

                label_x = col_x + key_zone_w + int(4 * s)
                parts.append(
                    f'  <text x="{label_x:.1f}" y="{row_mid + label_fs*0.35:.1f}" '
                    f'font-family="{FONT_FAMILY}" font-size="{label_fs}" font-weight="500" fill="#cad3f5">'
                    f'{html.escape(it["label"])}</text>'
                )
                y += row_h

    render_column(left_sections, card_x + pad_x)
    render_column(right_sections, card_x + pad_x + col_w + col_gap)

    # Footer mnemonic bar
    foot_y = card_y + card_h - pad_bot - int(18 * s)
    parts.append(
        f'  <line x1="{card_x + pad_x}" y1="{foot_y - int(42*s)}" '
        f'x2="{card_x + card_w - pad_x}" y2="{foot_y - int(42*s)}" '
        f'stroke="#363a4f" stroke-width="{max(1, int(1.8*s))}"/>'
    )
    mnemonics = "   ·   ".join(data["mnemonics"])
    parts.append(
        f'  <text x="{card_x + pad_x}" y="{foot_y}" '
        f'font-family="{FONT_FAMILY}" font-size="{footer_fs}" font-weight="700" fill="#eed49f">TIP</text>'
    )
    parts.append(
        f'  <text x="{card_x + pad_x + int(76*s)}" y="{foot_y}" '
        f'font-family="{FONT_FAMILY}" font-size="{footer_fs}" font-weight="400" fill="#a5adcb">'
        f'{html.escape(mnemonics)}</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    for tool in ("rsvg-convert", "magick"):
        if not shutil.which(tool):
            sys.stderr.write(f"Required tool not found in PATH: {tool}\n")
            return 1

    cfg_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    base_img = find_base_image()
    mod = load_cheatsheet_module()
    data = mod.build_data(cfg_path)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="herdr-wp-") as tmp:
        tmp_dir = Path(tmp)
        for filename, w, h, top_r, bot_r, left_r in TARGETS:
            svg_path = tmp_dir / f"{filename}.svg"
            overlay_png = tmp_dir / f"{filename}.overlay.png"
            out_path = OUT_DIR / filename

            svg_content = build_svg(data, w, h, top_r, bot_r, left_r)
            svg_path.write_text(svg_content, encoding="utf-8")

            subprocess.run(
                ["rsvg-convert", "-w", str(w), "-h", str(h), "-o", str(overlay_png), str(svg_path)],
                check=True,
            )
            subprocess.run(
                [
                    "magick",
                    str(base_img),
                    "-resize",
                    f"{w}x{h}^",
                    "-gravity",
                    "West",
                    "-extent",
                    f"{w}x{h}",
                    str(overlay_png),
                    "-gravity",
                    "NorthWest",
                    "-composite",
                    "-strip",
                    str(out_path),
                ],
                check=True,
            )
            print(f"[OK] {out_path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
