#!/usr/bin/env python3
"""Interactive Herdr keybindings cheatsheet popup.

Single source of truth:
- Parses live keys & [[keys.command]] from ~/.config/herdr/config.toml (or $HERDR_CONFIG_PATH)
- Backfills unmodified default keys from `herdr --default-config`
- Renders a responsive 3-column Catppuccin Macchiato TUI popup (q / Esc / Enter to close, / to filter)
- Supports `--dump-json` for wallpaper generator & promo video reuse.
"""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import tty
import unicodedata
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for system Python 3.9
    tomllib = None


# Catppuccin Macchiato ANSI truecolor helpers
def fg(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"\033[38;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


def bg(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"\033[48;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

C_BASE = "#24273a"
C_MANTLE = "#1e2030"
C_SURFACE0 = "#363a4f"
C_SURFACE1 = "#494d64"
C_OVERLAY0 = "#6e738d"
C_OVERLAY1 = "#8087a2"
C_SUBTEXT0 = "#a5adcb"
C_TEXT = "#cad3f5"
C_CYAN = "#18ecff"
C_GOLD = "#eed49f"
C_GREEN = "#a6da95"
C_TEAL = "#8bd5ca"
C_MAUVE = "#c6a0f6"
C_RED = "#ed8796"
C_BLUE = "#8aadf4"


# Fallback defaults if `herdr` CLI is unavailable in PATH
FALLBACK_DEFAULTS: dict[str, str] = {
    "prefix": "ctrl+b",
    "help": "prefix+?",
    "settings": "prefix+s",
    "detach": "prefix+q",
    "reload_config": "prefix+shift+r",
    "open_notification_target": "prefix+o",
    "workspace_picker": "prefix+w",
    "goto": "prefix+g",
    "new_workspace": "prefix+shift+n",
    "new_worktree": "prefix+shift+g",
    "rename_workspace": "prefix+shift+w",
    "close_workspace": "prefix+shift+d",
    "new_tab": "prefix+c",
    "rename_tab": "prefix+shift+t",
    "previous_tab": "prefix+p",
    "next_tab": "prefix+n",
    "switch_tab": "prefix+1..9",
    "close_tab": "prefix+shift+x",
    "rename_pane": "prefix+shift+p",
    "edit_scrollback": "prefix+e",
    "focus_pane_left": "prefix+h",
    "focus_pane_down": "prefix+j",
    "focus_pane_up": "prefix+k",
    "focus_pane_right": "prefix+l",
    "split_vertical": "prefix+v",
    "split_horizontal": "prefix+minus",
    "close_pane": "prefix+x",
    "zoom": "prefix+z",
    "resize_mode": "prefix+r",
    "toggle_sidebar": "prefix+b",
}


def resolve_config_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_path = os.environ.get("HERDR_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".config" / "herdr" / "config.toml"


def _parse_toml_fallback(text: str) -> dict[str, Any]:
    """Minimal fallback parser for [keys] and [[keys.command]] on Python <3.11."""
    result: dict[str, Any] = {"keys": {"command": []}}
    section = ""
    current_cmd: dict[str, Any] | None = None

    def parse_val(raw: str) -> Any:
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                return []
            return [m.group(1) for m in re.finditer(r'"((?:\\.|[^"\\])*)"', inner)]
        if raw.startswith('"') and raw.endswith('"'):
            return raw[1:-1].replace('\\"', '"')
        return raw

    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        in_q = False
        cleaned = []
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == '"' and (i == 0 or s[i - 1] != "\\"):
                in_q = not in_q
            if ch == "#" and not in_q:
                break
            cleaned.append(ch)
            i += 1
        s = "".join(cleaned).strip()
        if not s:
            continue
        if s == "[[keys.command]]":
            section = "keys.command"
            current_cmd = {}
            result["keys"]["command"].append(current_cmd)
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip()
            current_cmd = None
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            k = k.strip()
            val = parse_val(v)
            if section == "keys":
                result["keys"][k] = val
            elif section == "keys.command" and current_cmd is not None:
                current_cmd[k] = val
    return result


def load_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return _parse_toml_fallback(text)


def load_default_keys() -> dict[str, str]:
    defaults = dict(FALLBACK_DEFAULTS)
    herdr_bin = os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr")
    if not herdr_bin:
        for cand in ("/opt/homebrew/bin/herdr", "/usr/local/bin/herdr"):
            if Path(cand).exists():
                herdr_bin = cand
                break
    if not herdr_bin:
        return defaults
    try:
        proc = subprocess.run(
            [herdr_bin, "--default-config"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode != 0:
            return defaults
    except Exception:
        return defaults

    in_keys = False
    for line in proc.stdout.splitlines():
        s = line.strip()
        if s == "[keys]":
            in_keys = True
            continue
        if in_keys and s.startswith("[") and not s.startswith("#"):
            break
        if not in_keys:
            continue
        m = re.match(r'^#\s*([a-z_]+)\s*=\s*"([^"]*)"', s)
        if m:
            k, v = m.group(1), m.group(2)
            if v:
                defaults[k] = v
    return defaults


def normalize_bindings(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


TOKEN_MAP = {
    "cmd": "Cmd",
    "super": "Cmd",
    "alt": "Alt",
    "opt": "Alt",
    "ctrl": "Ctrl",
    "shift": "⇧",
    "tab": "Tab",
    "enter": "Enter",
    "esc": "Esc",
    "space": "Space",
    "slash": "/",
    "minus": "-",
    "plus": "+",
    "comma": ",",
    "period": ".",
    "backtick": "`",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
}


def format_key(raw: str, prefix_label: str) -> str:
    s = raw.strip()
    if s.startswith("prefix+"):
        rest = s[len("prefix+") :]
        return f"{prefix_label} {format_key(rest, prefix_label)}"
    parts = [p for p in s.split("+") if p]
    out: list[str] = []
    for p in parts:
        low = p.lower()
        if low in TOKEN_MAP:
            out.append(TOKEN_MAP[low])
        elif re.fullmatch(r"f\d{1,2}", low):
            out.append(low.upper())
        elif len(p) == 1 and p.isalpha():
            out.append(p.upper())
        else:
            out.append(p)
    return "+".join(out)


def compact_prefix(prefix_raw: str) -> str:
    if prefix_raw.lower() == "ctrl+b":
        return "^B"
    if prefix_raw.lower() == "ctrl+a":
        return "^A"
    return format_key(prefix_raw, "")


def is_prefix_only(raw: str) -> bool:
    return raw.strip().startswith("prefix+")


def split_primary_fallback(bindings: list[str], prefix_label: str) -> tuple[str, str]:
    direct = [format_key(b, prefix_label) for b in bindings if not is_prefix_only(b)]
    prefixed = [format_key(b, prefix_label) for b in bindings if is_prefix_only(b)]
    if direct:
        primary = " / ".join(direct)
        fallback = " · ".join(prefixed) if prefixed else ""
        return primary, fallback
    if prefixed:
        return " / ".join(prefixed), ""
    return "", ""


def build_data(config_path: Path) -> dict[str, Any]:
    cfg = load_toml(config_path)
    user_keys = cfg.get("keys", {}) or {}
    defaults = load_default_keys()
    prefix_raw = str(user_keys.get("prefix") or defaults.get("prefix") or "ctrl+b")
    prefix_short = compact_prefix(prefix_raw)

    def get_bindings(action: str) -> list[str]:
        if action in user_keys:
            return normalize_bindings(user_keys[action])
        return normalize_bindings(defaults.get(action, ""))

    def combined_hjkl(prefix_name: str) -> tuple[str, str]:
        dirs = [get_bindings(f"{prefix_name}_{d}") for d in ("left", "down", "up", "right")]
        direct_mods: list[str] = []
        pref_mods: list[str] = []
        for idx, letter in enumerate(("h", "j", "k", "l")):
            b = dirs[idx]
            d_match = next((x for x in b if x.lower().endswith("+" + letter) and not x.startswith("prefix+")), None)
            p_match = next((x for x in b if x.lower() == f"prefix+{letter}"), None)
            if d_match:
                direct_mods.append(d_match[: -(len(letter) + 1)])
            if p_match:
                pref_mods.append("prefix")
        if len(direct_mods) == 4 and len(set(direct_mods)) == 1:
            mod = format_key(direct_mods[0], prefix_short)
            primary = f"{mod}+H/J/K/L"
            fallback = f"{prefix_short} H/J/K/L" if len(pref_mods) == 4 else ""
            return primary, fallback
        parts = []
        for d, sym in (("left", "←"), ("down", "↓"), ("up", "↑"), ("right", "→")):
            p, _ = split_primary_fallback(get_bindings(f"{prefix_name}_{d}"), prefix_short)
            if p:
                parts.append(f"{sym}:{p}")
        return " ".join(parts), ""

    def item(action: str, label: str, note: str = "") -> dict[str, str] | None:
        b = get_bindings(action)
        if not b:
            return None
        primary, fallback = split_primary_fallback(b, prefix_short)
        if not primary:
            return None
        return {
            "action": action,
            "key": primary,
            "fallback": fallback,
            "label": label,
            "note": note,
        }

    def pair_item(a1: str, a2: str, label: str, note: str = "") -> dict[str, str] | None:
        p1, f1 = split_primary_fallback(get_bindings(a1), prefix_short)
        p2, f2 = split_primary_fallback(get_bindings(a2), prefix_short)
        if not p1 and not p2:
            return None
        key_str = f"{p1} / {p2}" if (p1 and p2) else (p1 or p2)
        if p1 and p2 and "+" in p1 and "+" in p2:
            m1, k1 = p1.rsplit("+", 1)
            m2, k2 = p2.rsplit("+", 1)
            if m1 == m2:
                key_str = f"{m1}+{k1} / {k2}"
        fb = ""
        if f1 and f2:
            fb = f"{f1} · {f2}"
        return {"action": f"{a1}/{a2}", "key": key_str, "fallback": fb, "label": label, "note": note}

    # Column 1: Panes (DWM + Vim / Alt layer)
    pane_items: list[dict[str, str]] = []
    for act_prefix, label in (
        ("focus_pane", "Focus pane"),
        ("swap_pane", "Swap pane position"),
        ("resize_pane", "Resize pane directly"),
    ):
        k, fb = combined_hjkl(act_prefix)
        if k:
            pane_items.append({"action": act_prefix, "key": k, "fallback": fb, "label": label, "note": ""})

    for row in (
        item("last_pane", "Last focused pane"),
        item("zoom", "Toggle pane zoom"),
        item("toggle_sidebar", "Toggle sidebar"),
        item("split_vertical", "Split vertical"),
        item("split_horizontal", "Split horizontal"),
        item("close_pane", "Close current pane"),
        item("copy_mode", "Vim copy mode"),
        item("edit_scrollback", "Edit scrollback"),
    ):
        if row:
            pane_items.append(row)

    # Column 2: Workspaces, Agents & Popups
    ws_agent_items: list[dict[str, str]] = []
    for row in (
        item("switch_workspace", "Go to space 1–9"),
        pair_item("previous_workspace", "next_workspace", "Prev / next space"),
        item("new_workspace", "New space"),
        item("rename_workspace", "Rename space"),
        item("next_agent", "Next agent"),
        item("previous_agent", "Previous agent"),
        item("focus_agent", "Agent #1–9 (queue)"),
        item("open_notification_target", "Go to alert agent"),
        item("goto", "Global fuzzy goto"),
    ):
        if row:
            ws_agent_items.append(row)

    # Custom [[keys.command]] popups
    commands = user_keys.get("command", []) or []
    desc_map = {
        "Git status": "Lazygit popup",
        "Keybindings cheatsheet": "This cheatsheet",
    }
    for cmd in commands:
        if not isinstance(cmd, dict):
            continue
        b = normalize_bindings(cmd.get("key"))
        if not b:
            continue
        primary, fallback = split_primary_fallback(b, prefix_short)
        raw_desc = str(cmd.get("description") or cmd.get("command") or "Custom popup")
        label = desc_map.get(raw_desc, raw_desc)
        ws_agent_items.append(
            {"action": "command", "key": primary, "fallback": fallback, "label": label, "note": "popup"}
        )

    # Column 3: Tabs (Cmd layer) + Fallback Prefix
    tab_items: list[dict[str, str]] = []
    for row in (
        item("new_tab", "New tab"),
        item("close_tab", "Close tab"),
        item("rename_tab", "Rename tab"),
        item("switch_tab", "Go to tab 1–9"),
        pair_item("previous_tab", "next_tab", "Prev / next tab"),
        pair_item("move_tab_previous", "move_tab_next", "Move tab left/right"),
    ):
        if row:
            tab_items.append(row)

    prefix_items: list[dict[str, str]] = []
    for act, label in (
        ("detach", "Detach session"),
        ("reload_config", "Reload config"),
        ("settings", "Open Herdr settings"),
        ("help", "Native Herdr help"),
        ("new_worktree", "New Git worktree"),
        ("workspace_picker", "Workspace picker"),
        ("resize_mode", "Enter resize mode"),
    ):
        row = item(act, label)
        if row:
            prefix_items.append(row)

    return {
        "config_path": str(config_path),
        "prefix": prefix_raw,
        "prefix_short": prefix_short,
        "mnemonics": [
            "Alt = Panes & Spaces (DWM)",
            "Cmd = Tabs & Lifecycle",
            "Shift = Heavier / Reverse",
            "Ctrl = Shell & Vim",
        ],
        "sections": [
            {"id": "panes", "title": "Panes · DWM + Vim", "badge": "Alt", "color": C_CYAN, "items": pane_items},
            {"id": "agents", "title": "Spaces & Agents", "badge": "Alt / Cmd", "color": C_GOLD, "items": ws_agent_items},
            {"id": "tabs", "title": "Tabs", "badge": "Cmd", "color": C_GREEN, "items": tab_items},
            {"id": "prefix", "title": f"Prefix Fallback · {prefix_short}", "badge": prefix_short, "color": C_MAUVE, "items": prefix_items},
        ],
    }


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    ea = unicodedata.east_asian_width(ch)
    return 2 if ea in ("W", "F") else 1


def disp_width(s: str) -> int:
    plain = re.sub(r"\033\[[0-9;]*m", "", s)
    return sum(char_width(c) for c in plain)


def trunc_plain(s: str, max_w: int) -> str:
    if max_w <= 0:
        return ""
    w = 0
    out = []
    for ch in s:
        cw = char_width(ch)
        if w + cw > max_w:
            if max_w >= 1 and out:
                while out and w + 1 > max_w:
                    w -= char_width(out.pop())
                out.append("…")
            break
        out.append(ch)
        w += cw
    return "".join(out)


def pad_ansi(s: str, target_w: int) -> str:
    w = disp_width(s)
    if w >= target_w:
        return s
    return s + (" " * (target_w - w))


def render_section_lines(section: dict[str, Any], col_w: int, query: str) -> list[str]:
    color = section["color"]
    q = query.lower().strip()
    items = section["items"]
    if q:
        items = [
            it
            for it in items
            if q in it["key"].lower() or q in it["label"].lower() or q in it["fallback"].lower() or q in section["title"].lower()
        ]
    if q and not items:
        return []

    lines: list[str] = []
    title_text = f" {section['title']} "
    badge_text = f"[{section['badge']}]"
    bar_w = max(1, col_w - disp_width(title_text) - disp_width(badge_text) - 2)
    header = (
        f"{BOLD}{fg(color)}▸{title_text}{RESET}"
        f"{fg(C_SURFACE1)}{'─' * bar_w}{RESET} "
        f"{fg(C_SUBTEXT0)}{badge_text}{RESET}"
    )
    lines.append(pad_ansi(header, col_w))

    key_col_w = min(22, max(14, int(col_w * 0.44)))

    for it in items:
        k_plain = trunc_plain(it["key"], key_col_w)
        pill_w = disp_width(k_plain) + 2
        gap = max(1, key_col_w + 2 - pill_w)
        l_max = max(4, col_w - 1 - pill_w - gap)
        l_plain = trunc_plain(it["label"], l_max)
        line = f" {bg(C_SURFACE0)}{BOLD}{fg(color)} {k_plain} {RESET}{' ' * gap}{fg(C_TEXT)}{l_plain}{RESET}"
        lines.append(pad_ansi(line, col_w))

    return lines


def render_screen(data: dict[str, Any], query: str, filtering: bool) -> str:
    size = shutil.get_terminal_size((120, 36))
    cols = max(50, size.columns)
    rows = max(16, size.lines)

    out: list[str] = ["\033[H\033[2J"]

    # Header
    title = " HERDR · DWM + VIM KEYMAP "
    sub = "source: ~/.config/herdr/config.toml"
    pad_hdr = max(1, cols - disp_width(title) - disp_width(sub) - 2)
    out.append(
        f"{bg(C_MANTLE)}{BOLD}{fg(C_CYAN)}{title}{RESET}"
        f"{bg(C_MANTLE)}{' ' * pad_hdr}{fg(C_OVERLAY1)}{sub}  {RESET}"
    )
    out.append(f"{fg(C_SURFACE1)}{'━' * cols}{RESET}")

    secs = {s["id"]: s for s in data["sections"]}
    body_h = rows - 5

    if cols >= 114:
        gap = 3
        col_w = (cols - 2 - gap * 2) // 3
        c1 = render_section_lines(secs["panes"], col_w, query)
        c2 = render_section_lines(secs["agents"], col_w, query)
        c3_top = render_section_lines(secs["tabs"], col_w, query)
        c3_bot = render_section_lines(secs["prefix"], col_w, query)
        c3 = c3_top + ([""] if (c3_top and c3_bot) else []) + c3_bot
        max_h = max(len(c1), len(c2), len(c3), 1)
        sep = f" {fg(C_SURFACE1)}│{RESET} "
        for i in range(min(max_h, body_h)):
            l1 = c1[i] if i < len(c1) else " " * col_w
            l2 = c2[i] if i < len(c2) else " " * col_w
            l3 = c3[i] if i < len(c3) else " " * col_w
            out.append(f" {pad_ansi(l1, col_w)}{sep}{pad_ansi(l2, col_w)}{sep}{pad_ansi(l3, col_w)}")
        rendered_rows = min(max_h, body_h)
    elif cols >= 76:
        gap = 3
        col_w = (cols - 2 - gap) // 2
        left = render_section_lines(secs["panes"], col_w, query)
        t_lines = render_section_lines(secs["tabs"], col_w, query)
        if left and t_lines:
            left = left + [""] + t_lines
        else:
            left = left or t_lines
        right = render_section_lines(secs["agents"], col_w, query)
        p_lines = render_section_lines(secs["prefix"], col_w, query)
        if right and p_lines:
            right = right + [""] + p_lines
        else:
            right = right or p_lines
        max_h = max(len(left), len(right), 1)
        sep = f" {fg(C_SURFACE1)}│{RESET} "
        for i in range(min(max_h, body_h)):
            l1 = left[i] if i < len(left) else " " * col_w
            l2 = right[i] if i < len(right) else " " * col_w
            out.append(f" {pad_ansi(l1, col_w)}{sep}{pad_ansi(l2, col_w)}")
        rendered_rows = min(max_h, body_h)
    else:
        col_w = cols - 2
        merged: list[str] = []
        for s in data["sections"]:
            part = render_section_lines(s, col_w, query)
            if part:
                if merged:
                    merged.append("")
                merged.extend(part)
        for i in range(min(len(merged), body_h)):
            out.append(" " + merged[i])
        rendered_rows = min(len(merged), body_h)

    if query and rendered_rows == 0:
        out.append(f"\n  {fg(C_RED)}No matches for: {query}{RESET}")
        rendered_rows = 2

    for _ in range(max(0, body_h - rendered_rows)):
        out.append("")

    # Footer
    out.append(f"{fg(C_SURFACE1)}{'─' * cols}{RESET}")
    mnemonic_str = "  ·  ".join(data["mnemonics"])
    out.append(f" {fg(C_GOLD)}TIP{RESET}  {fg(C_SUBTEXT0)}{trunc_plain(mnemonic_str, cols - 7)}{RESET}")
    if filtering:
        bar = f" {bg(C_SURFACE0)}{BOLD}{fg(C_CYAN)} / {query}▌ {RESET}  {fg(C_OVERLAY1)}[Enter] confirm  [Esc] clear{RESET}"
    elif query:
        bar = f" {fg(C_TEAL)}Filter: \"{query}\"{RESET}  {fg(C_OVERLAY1)}[/] edit  [Esc] clear  [q / Enter] close{RESET}"
    else:
        bar = f" {fg(C_OVERLAY1)}[/] filter   [r] reload config   [q / Esc / Enter] close{RESET}"
    out.append(bar)
    return "\r\n".join(out)


def run_tui(config_path: Path) -> None:
    data = build_data(config_path)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stdout.write(render_screen(data, "", False) + "\n")
        return

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    query = ""
    filtering = False
    dirty = True

    def on_winch(_signum: int, _frame: Any) -> None:
        nonlocal dirty
        dirty = True

    signal.signal(signal.SIGWINCH, on_winch)

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?1049h\033[?25l")
        sys.stdout.flush()

        while True:
            if dirty:
                sys.stdout.write(render_screen(data, query, filtering))
                sys.stdout.flush()
                dirty = False

            rlist, _, _ = select.select([fd], [], [], 0.1)
            if not rlist:
                continue
            raw = os.read(fd, 16)
            if not raw:
                break

            if raw in (b"\x03", b"\x04"):
                break

            if filtering:
                if raw == b"\x1b":
                    filtering = False
                    query = ""
                    dirty = True
                elif raw in (b"\r", b"\n"):
                    filtering = False
                    dirty = True
                elif raw in (b"\x7f", b"\x08"):
                    query = query[:-1]
                    dirty = True
                else:
                    try:
                        text = raw.decode("utf-8", errors="ignore")
                        printable = "".join(ch for ch in text if ch.isprintable())
                        if printable:
                            query += printable
                            dirty = True
                    except Exception:
                        pass
            else:
                if raw in (b"q", b"Q", b"\r", b"\n", b" "):
                    break
                if raw == b"\x1b":
                    if query:
                        query = ""
                        dirty = True
                    else:
                        break
                elif raw == b"/":
                    filtering = True
                    dirty = True
                elif raw in (b"r", b"R"):
                    data = build_data(config_path)
                    dirty = True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


def main() -> int:
    args = sys.argv[1:]
    cfg_arg: str | None = None
    dump_json = False
    i = 0
    while i < len(args):
        if args[i] == "--dump-json":
            dump_json = True
        elif args[i] == "--config" and i + 1 < len(args):
            cfg_arg = args[i + 1]
            i += 1
        i += 1

    cfg_path = resolve_config_path(cfg_arg)
    if not cfg_path.exists():
        sys.stderr.write(f"herdr config not found: {cfg_path}\n")
        return 1

    if dump_json:
        print(json.dumps(build_data(cfg_path), ensure_ascii=False, indent=2))
        return 0

    run_tui(cfg_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
