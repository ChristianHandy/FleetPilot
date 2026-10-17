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


def share(m):
    return round(100 * m["ai"] / m["all"], 1) if m["all"] else 0.0


def svg(months):
    """A bar chart of the monthly AI share; readable on GitHub's light and dark themes."""
    items = list(months.items())
    total = {k: sum(m[k] for _, m in items) for k in ("ai", "all")}
    overall = share(total)
    w, h, left, top, bottom = 760, 310, 48, 66, 44
    plot_h = h - top - bottom
    step = (w - left - 16) / max(len(items), 1)
    bar = min(46, step * 0.62)
    grey, accent = "#8b949e", "#e5534b"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
           f'aria-labelledby="t d" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
           '<title id="t">Share of FleetPilot code written with AI assistance, per month</title>',
           '<desc id="d">' + escape("; ".join(f"{k}: {share(m)} % of changed lines" for k, m in items)
                                    + f". Overall: {overall} %. Goal: as low as possible.") + "</desc>",
           f'<text x="{left}" y="22" font-size="16" font-weight="700" fill="{grey}">'
           f'AI-assisted share of changed lines per month</text>',
           f'<text x="{left}" y="42" font-size="12.5" fill="{grey}">Overall {overall} % · '
           f'goal: as low as we can get · counts only declared AI help</text>']
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
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--svg")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    months = monthly(args.ref)
    if not months:
        print("no commits found (is this a shallow clone?)", file=sys.stderr)
        return 1
    for month, m in months.items():
        print(f"{month}  {share(m):5.1f} % of {m['all']:7d} lines  ({m['ai_commits']}/{m['commits']} commits)")
    if args.svg:
        with open(args.svg, "w", encoding="utf-8") as fh:
            fh.write(svg(months))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({k: dict(v, share=share(v)) for k, v in months.items()}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
