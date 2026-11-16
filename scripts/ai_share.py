# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""How much of FleetPilot's code was written with AI assistance, per month.

    python scripts/ai_share.py [--svg OUT.svg] [--json OUT.json] [--ref origin/main]

Reads the git history (it needs the full history, not a shallow clone) and counts
the lines each commit changed (added + deleted). A commit counts as AI-assisted when
its author is a known coding agent, or its message names an AI co-author or tool
(see AI_AUTHORS and AI_MESSAGE). Dependency bots are left out entirely. The project
goal is to bring this share down as far as possible (ROADMAP.md).

The figure is a lower bound: AI help that a commit does not declare is not counted.

    python scripts/ai_share.py --codebase-json OUT.json --badge OUT.svg

The codebase share answers a different question: of the code as it is now, how many
lines come from AI-assisted commits? It runs git blame on every tracked code file and
attributes each line to the commit that last changed it.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from collections import OrderedDict
from xml.sax.saxutils import escape

# Authors that are coding agents. The two local identities were agent sessions
# (Manus) in June and August 2026.
AI_AUTHORS = re.compile(r"copilot-swe-agent|manus|@manus\.ai|fleetpilot@dev\.local|fleetpilot@datacenter\.local",
                        re.IGNORECASE)
# Co-author lines and tool footers that declare AI assistance.
AI_MESSAGE = re.compile(
    r"^co-authored-by:.*(anthropic\.com|claude|copilot|openai|chatgpt|gemini|powered by ai)"
    r"|generated with \[?(claude|copilot|chatgpt|cursor)",
    re.IGNORECASE | re.MULTILINE)
# Automation that is neither a person nor an AI writing code.
BOTS = re.compile(r"dependabot\[bot\]|github-actions\[bot\]|renovate\[bot\]", re.IGNORECASE)
# Files whose size says nothing about who wrote the code.
SKIP_FILES = re.compile(r"(^|/)(requirements[\w-]*-lock\.txt|package-lock\.json)$|\.(png|jpe?g|webp|pdf|svg|ico)$")

SEP = "\x1e"


def commits(ref):
    """Yield (month, is_ai, is_bot, lines) for every non-merge commit reachable from ``ref``."""
    out = subprocess.run(
        ["git", "log", ref, "--no-merges", "--numstat", f"--format={SEP}%ad%x00%an <%ae>%x00%B%x00",
         "--date=format:%Y-%m"],
        check=True, capture_output=True, text=True, errors="replace").stdout
    for record in out.split(SEP)[1:]:
        month, author, message, stats = record.split("\x00", 3)
        lines = 0
        for row in stats.strip().splitlines():
            parts = row.split("\t")
            if len(parts) == 3 and parts[0].isdigit() and not SKIP_FILES.search(parts[2]):
                lines += int(parts[0]) + int(parts[1])
        is_bot = bool(BOTS.search(author))
        is_ai = not is_bot and bool(AI_AUTHORS.search(author) or AI_MESSAGE.search(message))
        yield month, is_ai, is_bot, lines


def monthly(ref):
    """{month: {"ai": lines, "all": lines, "ai_commits": n, "commits": n}}, bots excluded, oldest first."""
    months = {}
    for month, is_ai, is_bot, lines in commits(ref):
        if is_bot:
            continue
        m = months.setdefault(month, {"ai": 0, "all": 0, "ai_commits": 0, "commits": 0})
        m["all"] += lines
        m["commits"] += 1
        if is_ai:
            m["ai"] += lines
            m["ai_commits"] += 1
    return OrderedDict(sorted(months.items()))


# Code the codebase share counts; vendored libraries are not ours.
CODE_FILES = re.compile(r"\.(py|sh|js|ts|css|html|j2|kt|kts|cs|ps1|yml|yaml|toml|ini|conf|service)$|"
                        r"^scripts/fleetpilot-")
NOT_OURS = re.compile(r"(^|/)(vendor|node_modules|dist|build)/|\.min\.(js|css)$")


def ai_commit_shas(ref):
    """(AI-assisted commit SHAs, bot commit SHAs) reachable from ``ref``."""
    out = subprocess.run(["git", "log", ref, f"--format={SEP}%H%x00%an <%ae>%x00%B"],
                         check=True, capture_output=True, text=True, errors="replace").stdout
    ai, bots = set(), set()
    for record in out.split(SEP)[1:]:
        sha, author, message = (record.split("\x00", 2) + ["", ""])[:3]
        if BOTS.search(author):
            bots.add(sha)
        elif AI_AUTHORS.search(author) or AI_MESSAGE.search(message):
            ai.add(sha)
    return ai, bots


def blame_counts(ref, path):
    """{commit sha: lines} for the current lines of ``path`` at ``ref``."""
    out = subprocess.run(["git", "blame", "--incremental", "-w", "-M", ref, "--", path],
                         check=True, capture_output=True, text=True, errors="replace").stdout
    counts = {}
    for line in out.splitlines():
        parts = line.split(" ")
        if len(parts) == 4 and len(parts[0]) == 40 and all(p.isdigit() for p in parts[1:]):
            counts[parts[0]] = counts.get(parts[0], 0) + int(parts[3])
    return counts


def codebase(ref="HEAD"):
    """AI share of the code as it is at ``ref``: totals and a breakdown per top-level area."""
    ai, bots = ai_commit_shas(ref)
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref], check=True, capture_output=True,
                           text=True).stdout.splitlines()
    total = {"ai": 0, "all": 0, "files": 0}
    areas = {}
    for path in files:
        if not CODE_FILES.search(path) or NOT_OURS.search(path) or SKIP_FILES.search(path):
            continue
        counts = blame_counts(ref, path)
        lines = sum(n for sha, n in counts.items() if sha not in bots)
        ai_lines = sum(n for sha, n in counts.items() if sha in ai)
        if not lines:
            continue
        area = path.split("/", 1)[0] if "/" in path else ("tests" if path.startswith("test_") else "core")
        a = areas.setdefault(area, {"ai": 0, "all": 0})
        a["ai"] += ai_lines
        a["all"] += lines
        total["ai"] += ai_lines
        total["all"] += lines
        total["files"] += 1
    result = dict(total, share=share(total), ref=ref,
                  areas={k: dict(v, share=share(v)) for k, v in sorted(areas.items(), key=lambda kv: -kv[1]["all"])})
    return result


def month_end_commits(ref, months):
    """{month: the last commit of that month reachable from ``ref``}."""
    out = {}
    for month in months:
        year, mon = int(month[:4]), int(month[5:])
        after = f"{year + 1}-01-01" if mon == 12 else f"{year}-{mon + 1:02d}-01"
        sha = subprocess.run(["git", "rev-list", "-1", f"--before={after}", ref], check=True,
                             capture_output=True, text=True).stdout.strip()
        if sha:
            out[month] = sha
    return out


def trend(ref, months):
    """{month: AI share of the whole code at the end of that month}, by git blame."""
    return {month: codebase(sha)["share"] for month, sha in month_end_commits(ref, months).items()}


def direction(code_trend):
    """("up" | "down" | "flat", change in percentage points, previous month) for the last two months, or None."""
    items = list(code_trend.items())
    if len(items) < 2:
        return None
    (prev_month, prev), (_, last) = items[-2], items[-1]
    change = round(last - prev, 1)
    return ("up" if change >= 0.5 else "down" if change <= -0.5 else "flat"), change, prev_month


def badge(percent):
    """A flat badge "AI-written code | NN %", readable on light and dark backgrounds."""
    label, value = "AI-written code", f"{percent:.0f} %"
    lw, vw = 7 * len(label) + 12, 7 * len(value) + 14
    colour = "#2f9e44" if percent < 25 else "#e8a317" if percent < 60 else "#d64545"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img" '
            f'aria-label="{label}: {value}"><title>{label}: {value}</title>'
            f'<rect width="{lw}" height="20" fill="#555"/><rect x="{lw}" width="{vw}" height="20" fill="{colour}"/>'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
            f'<text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{value}</text></g></svg>\n')


def share(m):
    return round(100 * m["ai"] / m["all"], 1) if m["all"] else 0.0


def svg(months, code_trend=None):
    """Bars: the monthly AI share of changed lines. Line: the AI share of all code at each month's end.

    Readable on GitHub's light and dark themes."""
    code_trend = code_trend or {}
    items = list(months.items())
    total = {k: sum(m[k] for _, m in items) for k in ("ai", "all")}
    overall = share(total)
    w, h, left, top, bottom = 760, 310, 48, 66, 44
    plot_h = h - top - bottom
    step = (w - left - 16) / max(len(items), 1)
    bar = min(46, step * 0.62)
    grey, accent, line = "#8b949e", "#e5534b", "#539bf5"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
           f'aria-labelledby="t d" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
           '<title id="t">Share of FleetPilot code written with AI assistance, per month</title>',
           '<desc id="d">' + escape("; ".join(
               f"{k}: {share(m)} % of changed lines"
               + (f", {code_trend[k]} % of all code at month end" if k in code_trend else "") for k, m in items)
               + f". Overall: {overall} %. Goal: as low as possible.") + "</desc>",
           f'<text x="{left}" y="22" font-size="16" font-weight="700" fill="{grey}">'
           f'AI-assisted code in FleetPilot</text>',
           f'<rect x="{left}" y="33" width="11" height="11" rx="2" fill="{accent}"/>'
           f'<text x="{left + 16}" y="42" font-size="12.5" fill="{grey}">changed lines per month '
           f'(overall {overall} %)</text>']
    if code_trend:
        out.append(f'<line x1="{left + 245}" x2="{left + 263}" y1="38.5" y2="38.5" stroke="{line}" stroke-width="3"/>'
                   f'<text x="{left + 269}" y="42" font-size="12.5" fill="{grey}">all code at month end</text>')
    out.append(f'<text x="{w - 10}" y="42" font-size="12.5" text-anchor="end" fill="{grey}">'
               f'goal: as low as we can get · declared AI help</text>')
    trend_now = direction(code_trend)
    if trend_now:
        way, change, since = trend_now
        since = datetime.date(int(since[:4]), int(since[5:]), 1).strftime("%b %Y")
        text, colour = {"up": (f"▲ going up: +{change} points since {since}", accent),
                        "down": (f"▼ going down: {change} points since {since}", "#3fb950"),
                        "flat": (f"► unchanged since {since}", grey)}[way]
        out.append(f'<text x="{w - 10}" y="22" font-size="14" font-weight="700" text-anchor="end" '
                   f'fill="{colour}">AI share of all code {text}</text>')
    for pct in (0, 25, 50, 75, 100):
        y = top + plot_h * (1 - pct / 100)
        out.append(f'<line x1="{left}" x2="{w - 10}" y1="{y:.1f}" y2="{y:.1f}" stroke="{grey}" stroke-opacity=".3" stroke-width="1"/>')
        out.append(f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="{grey}">{pct}%</text>')
    for i, (month, m) in enumerate(items):
        pct = share(m)
        x = left + step * i + (step - bar) / 2
        bh = plot_h * pct / 100
        label = datetime.date(int(month[:4]), int(month[5:]), 1).strftime("%b %Y")
        out.append(f'<rect x="{x:.1f}" y="{top + plot_h - bh:.1f}" width="{bar:.1f}" height="{max(bh, 1):.1f}" '
                   f'rx="3" fill="{accent}"><title>{escape(label)}: {pct} % ({m["ai_commits"]} of '
                   f'{m["commits"]} commits)</title></rect>')
        inside = bh > 26   # the label goes into tall bars, so it never collides with the top grid line
        out.append(f'<text x="{x + bar / 2:.1f}" y="{top + plot_h - bh + (17 if inside else -6):.1f}" font-size="11.5" '
                   f'font-weight="700" text-anchor="middle" fill="{"#ffffff" if inside else grey}">{pct:.0f}%</text>')
        out.append(f'<text x="{x + bar / 2:.1f}" y="{h - bottom + 18}" font-size="11" text-anchor="middle" '
                   f'fill="{grey}">{escape(label)}</text>')
    points = [(left + step * i + step / 2, top + plot_h * (1 - code_trend[month] / 100), code_trend[month], month)
              for i, (month, _) in enumerate(items) if month in code_trend]
    if points:
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in points)}" fill="none" '
                   f'stroke="{line}" stroke-width="3" stroke-linejoin="round"/>')
        for x, y, pct, month in points:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{line}"><title>{escape(month)}: '
                       f'{pct} % of all code</title></circle>')
            out.append(f'<text x="{x + 8:.1f}" y="{y - 7:.1f}" font-size="11.5" font-weight="700" fill="{line}">'
                       f'{pct:.0f}%</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--svg")
    parser.add_argument("--json")
    parser.add_argument("--codebase-json", help="write the AI share of the current code (git blame) here")
    parser.add_argument("--badge", help="write a badge with the current code's AI share here")
    args = parser.parse_args(argv)
    if args.codebase_json or args.badge:
        current = codebase(args.ref)
        print(f"current code: {current['share']:.1f} % of {current['all']} lines in {current['files']} files "
              f"come from AI-assisted commits")
        for area, a in current["areas"].items():
            print(f"  {area:<20} {a['share']:5.1f} % of {a['all']:6d} lines")
        if args.codebase_json:
            with open(args.codebase_json, "w", encoding="utf-8") as fh:
                json.dump(current, fh, indent=2)
        if args.badge:
            with open(args.badge, "w", encoding="utf-8") as fh:
                fh.write(badge(current["share"]))
        if not (args.svg or args.json):
            return 0
    months = monthly(args.ref)
    if not months:
        print("no commits found (is this a shallow clone?)", file=sys.stderr)
        return 1
    for month, m in months.items():
        print(f"{month}  {share(m):5.1f} % of {m['all']:7d} lines  ({m['ai_commits']}/{m['commits']} commits)")
    code_trend = trend(args.ref, months)
    for month, pct in code_trend.items():
        print(f"{month}  all code at month end: {pct:5.1f} %")
    if direction(code_trend):
        way, change, since = direction(code_trend)
        print(f"AI share of all code is going {way} ({change:+} points since {since})")
    if args.svg:
        with open(args.svg, "w", encoding="utf-8") as fh:
            fh.write(svg(months, code_trend))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({k: dict(v, share=share(v), codebase_share=code_trend.get(k)) for k, v in months.items()},
                      fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
