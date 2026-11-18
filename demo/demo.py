"""Scripted demo: real Claude Code sessions driving Archicad through this MCP server.

Run on the Windows machine that has Archicad open (inside the desktop session):
    uv run python demo/demo.py --record demo/out/raw.mkv

It places Archicad on the left and this console on the right, optionally records the screen
with ffmpeg (gdigrab), sends the prompts below to `claude -p` (one conversation, resumed turn by
turn) and prints the conversation and every tool call as it happens. Segment start times are
written next to the recording for captioning.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

PROMPTS = [
    ("Part 1 - Find & check",
     "I'm checking fire ratings in this Archicad project. Which doors have no fire rating, per storey? "
     "Show the ones on the ground floor to me in red in Archicad. Then check their door types and host walls "
     "and propose a fire rating rule. Don't change anything yet."),
    ("Part 1 - Preview",
     "Good. Rule: EI60 for doors in 300 mm walls, EI30 for doors in 150 mm walls, leave the others empty. "
     "Preview the change first."),
    ("Part 1 - Confirm & fix",
     "Confirmed, apply it. Then show the fixed ground floor doors in green and give me the before/after count per storey."),
    ("Part 2 - Wall cost estimate",
     "Now act as a quantity surveyor. Price every wall by type, read-only. Test rates in USD per m2 by thickness: "
     "300 mm 46, 200 mm 34, 190 mm 33, 150 mm 28, 100 mm 22, 50 mm 16, 30 mm 13.6; glass walls low/mid/high 180/220/260. "
     "Use net area, low/high = mid -/+ 15%, exclude the 20 mm walls, no hidden layers. Export to Excel and "
     "summarise the totals and the assumptions."),
]

ALLOWED = ",".join(f"mcp__archicad__{t}" for t in [
    "project_overview", "resolve_names", "show_in_archicad", "find_doors_missing_property", "inspect_doors",
    "preview_property_update", "apply_property_update", "wall_takeoff", "price_walls"])

STYLE = ("This is a live demo shown in a narrow console. Keep every answer short: at most 12 lines, "
         "tables with at most 4 short columns, no headings, no long caveats. Mention assumptions in one line.")

C = {"dim": "\x1b[2m", "b": "\x1b[1m", "cyan": "\x1b[96m", "yel": "\x1b[93m", "grn": "\x1b[92m", "mag": "\x1b[95m", "x": "\x1b[0m"}
WIDTH = max(60, min(110, shutil.get_terminal_size((92, 40)).columns - 2))


def say(s=""):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def wrap(text, indent="  "):
    out = []
    for para in text.splitlines():
        if not para.strip():
            out.append("")
            continue
        if para.lstrip().startswith("|"):  # keep markdown tables as they are
            out.append(indent + para[: WIDTH - len(indent)])
            continue
        out.extend(textwrap.wrap(para, WIDTH - len(indent), initial_indent=indent, subsequent_indent=indent) or [""])
    return "\n".join(out)


def type_out(text, delay=0.012):
    for line in textwrap.wrap(text, WIDTH - 4):
        sys.stdout.write("  " + C["cyan"] + C["b"])
        for ch in line:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(delay)
        sys.stdout.write(C["x"] + "\n")


def place_windows():
    """Archicad on the left 60 %, this console on the right 40 % (Windows only)."""
    if os.name != "nt":
        return
    u = ctypes.windll.user32
    u.SetProcessDPIAware()
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    split = int(sw * 0.6)
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        n = u.GetWindowTextLengthW(h)
        if n and u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            if b.value.endswith("- Archicad 30"):
                found.append(h)
        return True

    u.EnumWindows(cb, 0)
    for h in found[:1]:
        u.ShowWindow(h, 9)  # restore from maximized
        u.SetWindowPos(h, 0, 0, 0, split, sh - 48, 0x0040)
    me = u.GetForegroundWindow()
    if me:
        u.SetWindowPos(me, 0, split, 0, sw - split, sh - 48, 0x0040)


def run_turn(i, title, prompt, session, log):
    say()
    say(f"{C['mag']}{C['b']}━━ {title} {'━' * max(0, WIDTH - len(title) - 4)}{C['x']}")
    say(f"{C['dim']}  You:{C['x']}")
    type_out(prompt)
    say()
    log.append({"segment": title, "t": time.time()})
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--allowedTools", ALLOWED,
           "--append-system-prompt", STYLE]
    cmd += ["--session-id", session] if i == 0 else ["--resume", session]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use":
                    name = c["name"].replace("mcp__archicad__", "")
                    args = json.dumps(c.get("input", {}), ensure_ascii=False)
                    args = args if len(args) < 70 else args[:67] + "..."
                    say(f"  {C['yel']}⚙ {name}{C['x']} {C['dim']}{args}{C['x']}")
                elif c.get("type") == "text" and c["text"].strip():
                    say(f"{C['dim']}  Claude:{C['x']}")
                    say(wrap(c["text"]))
        elif ev.get("type") == "user":
            for c in ev.get("message", {}).get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    ok = not c.get("is_error")
                    say(f"    {C['grn'] if ok else C['yel']}{'✓' if ok else '✗'} done{C['x']}")
        elif ev.get("type") == "result":
            secs = ev.get("duration_ms", 0) / 1000
            say(f"{C['dim']}  ({secs:.0f} s){C['x']}")
    p.wait()


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    link = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    return str(link) if link.exists() else "ffmpeg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", help="screen recording output (.mkv), needs ffmpeg")
    ap.add_argument("--only", type=int, nargs="*", help="run only these prompt numbers (0-based)")
    ap.add_argument("--no-excel", dest="open_excel", action="store_false")
    a = ap.parse_args()
    os.system("")  # enable ANSI colours on Windows
    place_windows()
    rec = None
    log: list[dict] = []
    if a.record:
        Path(a.record).parent.mkdir(parents=True, exist_ok=True)
        rec = subprocess.Popen(
            [_ffmpeg(), "-y", "-loglevel", "error", "-f", "gdigrab", "-framerate", "15", "-draw_mouse", "1", "-i", "desktop",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", a.record],
            stdin=subprocess.PIPE)
        time.sleep(2)
    t0 = time.time()
    log.append({"segment": "start", "t": t0})
    say(f"{C['b']}  Archicad AI Productivity Tools{C['x']}  {C['dim']}Claude + MCP server + Tapir · Villa Patio sample{C['x']}")
    session = str(uuid.uuid4())
    for i, (title, prompt) in enumerate(PROMPTS):
        if a.only and i not in a.only:
            continue
        run_turn(i, title, prompt, session, log)
        time.sleep(2)
    if a.open_excel:
        out = Path.home() / "Documents" / "nemetschek-ai"
        xl = sorted(out.glob("wall-cost-estimate-*.xlsx"), key=lambda p: p.stat().st_mtime)
        if xl:
            log.append({"segment": "excel", "t": time.time()})
            say(f"\n  {C['grn']}Opening {xl[-1].name}{C['x']}")
            os.startfile(str(xl[-1]))  # type: ignore[attr-defined]
            time.sleep(12)
    log.append({"segment": "end", "t": time.time()})
    if rec:
        rec.stdin.write(b"q")
        rec.stdin.flush()
        rec.wait(timeout=60)
        Path(a.record).with_suffix(".segments.json").write_text(json.dumps([{**x, "t": round(x["t"] - t0, 1)} for x in log], indent=1))
    say(f"\n{C['dim']}  Demo finished in {time.time() - t0:.0f} s.{C['x']}")


if __name__ == "__main__":
    main()
