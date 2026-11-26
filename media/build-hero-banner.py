#!/usr/bin/env python3
"""Compose the GitHub README Hero Banner from the generated text-free artwork + vector typography."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

MEDIA_DIR = Path(__file__).resolve().parent
FONT = "Maple Mono NF CN"
W, H = 1600, 680

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="accentLine" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#18ecff" stop-opacity="0"/>
      <stop offset="25%" stop-color="#18ecff" stop-opacity="0.95"/>
      <stop offset="55%" stop-color="#eed49f" stop-opacity="0.9"/>
      <stop offset="80%" stop-color="#c6a0f6" stop-opacity="0.7"/>
      <stop offset="100%" stop-color="#c6a0f6" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="centerGlow" cx="50%" cy="48%" r="42%">
      <stop offset="0%" stop-color="#18ecff" stop-opacity="0.09"/>
      <stop offset="60%" stop-color="#1b1d2e" stop-opacity="0.03"/>
      <stop offset="100%" stop-color="#181926" stop-opacity="0"/>
    </radialGradient>
    <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="10" flood-color="#18ecff" flood-opacity="0.38"/>
    </filter>
  </defs>

  <!-- Subtle dark vignette in center to guarantee razor-sharp readability -->
  <rect x="270" y="54" width="1060" height="572" rx="28" fill="#181926" fill-opacity="0.52" stroke="#363a4f" stroke-opacity="0.45" stroke-width="1.5"/>
  <rect x="0" y="0" width="{W}" height="{H}" fill="url(#centerGlow)"/>

  <!-- Top org badge -->
  <rect x="688" y="102" width="224" height="38" rx="19" fill="#24273a" fill-opacity="0.9" stroke="#eed49f" stroke-opacity="0.45" stroke-width="1.4"/>
  <circle cx="714" cy="121" r="5" fill="#eed49f"/>
  <text x="808" y="128" text-anchor="middle" font-family="{FONT}" font-size="17" font-weight="600" fill="#eed49f" letter-spacing="1.4">MOStudio-AI</text>

  <!-- Main Title -->
  <text x="800" y="232" text-anchor="middle" font-family="{FONT}" font-size="68" font-weight="800" fill="#cad3f5" letter-spacing="-1">Herdr <tspan fill="#18ecff" filter="url(#softGlow)">×</tspan> Ghostty</text>

  <!-- Subtitle -->
  <text x="800" y="294" text-anchor="middle" font-family="{FONT}" font-size="25" font-weight="500" fill="#a5adcb">Leaderless DWM + Vim Multiplexing for Multi-Agent Workflows</text>

  <!-- Accent Divider -->
  <rect x="430" y="330" width="740" height="2.5" rx="1.2" fill="url(#accentLine)"/>

  <!-- 3-Layer Keycap Showcase Strip -->
  <g transform="translate(340, 368)">
    <!-- Pill 1: Alt -->
    <rect x="0" y="0" width="290" height="72" rx="14" fill="#24273a" fill-opacity="0.88" stroke="#18ecff" stroke-opacity="0.42" stroke-width="1.5"/>
    <text x="145" y="30" text-anchor="middle" font-family="{FONT}" font-size="18" font-weight="700" fill="#18ecff">Alt + H/J/K/L · 1..9</text>
    <text x="145" y="55" text-anchor="middle" font-family="{FONT}" font-size="15" font-weight="400" fill="#a5adcb">DWM Panes &amp; Workspaces</text>

    <!-- Pill 2: Cmd -->
    <rect x="315" y="0" width="290" height="72" rx="14" fill="#24273a" fill-opacity="0.88" stroke="#a6da95" stroke-opacity="0.42" stroke-width="1.5"/>
    <text x="460" y="30" text-anchor="middle" font-family="{FONT}" font-size="18" font-weight="700" fill="#a6da95">Cmd + T/W/B/K · /</text>
    <text x="460" y="55" text-anchor="middle" font-family="{FONT}" font-size="15" font-weight="400" fill="#a5adcb">Tabs · Sidebar · Cheatsheet</text>

    <!-- Pill 3: Ctrl -->
    <rect x="630" y="0" width="290" height="72" rx="14" fill="#24273a" fill-opacity="0.88" stroke="#eed49f" stroke-opacity="0.42" stroke-width="1.5"/>
    <text x="775" y="30" text-anchor="middle" font-family="{FONT}" font-size="18" font-weight="700" fill="#eed49f">Ctrl · Untouched</text>
    <text x="775" y="55" text-anchor="middle" font-family="{FONT}" font-size="15" font-weight="400" fill="#a5adcb">100% Clean for Shell &amp; Vim</text>
  </g>

  <!-- Feature tags footer -->
  <g transform="translate(392, 480)">
    <rect x="0" y="0" width="186" height="36" rx="18" fill="#363a4f" fill-opacity="0.72"/>
    <text x="93" y="24" text-anchor="middle" font-family="{FONT}" font-size="14.5" font-weight="500" fill="#cad3f5">Catppuccin Macchiato</text>

    <rect x="204" y="0" width="186" height="36" rx="18" fill="#363a4f" fill-opacity="0.72"/>
    <text x="297" y="24" text-anchor="middle" font-family="{FONT}" font-size="14.5" font-weight="500" fill="#18ecff">Neon Focus Shader</text>

    <rect x="408" y="0" width="196" height="36" rx="18" fill="#363a4f" fill-opacity="0.72"/>
    <text x="506" y="24" text-anchor="middle" font-family="{FONT}" font-size="14.5" font-weight="500" fill="#eed49f">Live Cmd+/ Popup</text>

    <rect x="622" y="0" width="194" height="36" rx="18" fill="#363a4f" fill-opacity="0.72"/>
    <text x="719" y="24" text-anchor="middle" font-family="{FONT}" font-size="14.5" font-weight="500" fill="#c6a0f6">5K Wallpaper Gen</text>
  </g>

  <!-- Bottom crisp tagline -->
  <text x="800" y="576" text-anchor="middle" font-family="{FONT}" font-size="16" font-weight="400" fill="#8087a2">macOS · Herdr 0.9.5+ · Ghostty 1.4+ · One-command symlink setup · MIT License</text>
</svg>
"""


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: build-hero-banner.py <base-artwork-path>\n")
        return 1
    base_img = Path(sys.argv[1]).expanduser()
    out_path = MEDIA_DIR / "hero-banner.png"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="herdr-hero-") as tmp:
        tmp_dir = Path(tmp)
        svg_path = tmp_dir / "hero.svg"
        overlay = tmp_dir / "hero.png"
        svg_path.write_text(SVG, encoding="utf-8")
        subprocess.run(["rsvg-convert", "-w", str(W), "-h", str(H), "-o", str(overlay), str(svg_path)], check=True)
        subprocess.run(
            [
                "magick",
                str(base_img),
                "-resize",
                f"{W}x{H}^",
                "-gravity",
                "Center",
                "-extent",
                f"{W}x{H}",
                str(overlay),
                "-gravity",
                "NorthWest",
                "-composite",
                "-strip",
                str(out_path),
            ],
            check=True,
        )
    print(f"[OK] {out_path} ({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
