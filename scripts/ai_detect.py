# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Report AI assistance in a pull request: what is declared, and style signs of what is not.

    python3 scripts/ai_detect.py BASE_SHA HEAD_SHA [--pr-body FILE]

Run by .github/workflows/pr-check.yml. The project accepts AI help as long as it is
named (ROADMAP.md, "Move away from AI-written code"), so this check never judges a
contribution; it makes AI help visible:

1. Declared: commits whose author is a coding agent or whose message names an AI
   co-author (the same rules as scripts/ai_share.py), and the answer in the pull
   request template's "AI assistance" section.
2. Style signals in the added lines that are typical of the AI-written code in this
   repository (box-drawing section dividers, check-mark emoji in messages, em dashes,
   boilerplate docstrings and stock phrases). This is an estimate, not proof: people
   write like this too, and AI output can look like anything.

It warns when the signals are strong but nothing is declared, and asks the author to
fill in the "AI assistance" section. It exits 0 either way unless --strict is given.

With --block-ai (used by the required check on pull requests) it fails whenever AI help
is declared or the style score is 50 or more: the project accepts only code written
without AI there. An empty "AI assistance" section alone only warns.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_share  # noqa: E402  (same declaration rules as the AI-share chart)

CODE = re.compile(r"\.(py|sh|js|ts|kt|kts|cs|ps1|html|j2|yml|yaml)$|^scripts/fleetpilot-")
SKIP = re.compile(r"(^|/)(test_[^/]*\.py|conftest\.py|ai_detect\.py)$|^(demo|fuzz|docs)/|-lock\.txt$")
MIN_LINES = 40          # fewer added code lines than this say too little to score
# Calibrated on this repository's history (October 2026, 153 commits): with this scale,
# a score of 50 or more is reached by about the top quarter of commits that declare AI help.
SCALE = 3

# (name, pattern, weight per hit, cap) - matched against added code lines.
SIGNALS = [
    ("section dividers", re.compile(r"[─━═]{3,}|^\s*#\s*[=\-]{10,}"), 6, 30),
    ("check-mark/emoji in output", re.compile("[✓✔✗✘⚠✅❌\U0001F300-\U0001FAFF]"), 4, 24),
    ("em dashes", re.compile("—"), 2, 16),
    ("stock phrases", re.compile(r"\b(comprehensive|robust|seamless(ly)?|leverag\w+|utiliz\w+|ensures? that|"
                                 r"note that|it is important|best practices?|for (better|improved) \w+)\b", re.I), 3, 18),
    ("labelled comments", re.compile(r"#\s*(Security|Note|Important|Safe|Step \d+|Fallback|Helper)\s*:", re.I), 3, 18),
    ("docstring sections", re.compile(r"^\s*(Args|Returns|Raises|Example[s]?)\s*:\s*$"), 2, 14),
]
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
NO_AI = re.compile(r"\b(no|none|not used|without|didn'?t use|did not use|nothing)\b", re.I)


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, errors="replace").stdout


def added_code_lines(diff_text):
    """[(path, text)] for added lines of code files, tests and generated files left out."""
    out, path = [], None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
            if path and (not CODE.search(path) or SKIP.search(path)):
                path = None
        elif raw.startswith("+") and path:
            out.append((path, raw[1:]))
    return out


def style_score(lines):
    """(score 0-100 or None when too little code, {signal: hits}) for the added lines."""
    if len(lines) < MIN_LINES:
        return None, {}
    hits = {name: 0 for name, *_ in SIGNALS}
    for _, text in lines:
        for name, pattern, _, _ in SIGNALS:
            hits[name] += len(pattern.findall(text))
    per_100 = 100 / len(lines)
    score = 0.0
    for name, _, weight, cap in SIGNALS:
        score += min(cap, hits[name] * per_100 * weight)
    return min(100, round(score * SCALE)), {k: v for k, v in hits.items() if v}


def declared_commits(span):
    """[(short sha, how)] for commits that declare AI help."""
    out = []
    log = git("log", "--no-merges", f"--format={ai_share.SEP}%h%x00%an <%ae>%x00%B", span)
    for record in log.split(ai_share.SEP)[1:]:
        sha, author, message = (record.split("\x00", 2) + ["", ""])[:3]
        if ai_share.BOTS.search(author):
            continue
        if ai_share.AI_AUTHORS.search(author):
            out.append((sha, f"author {author.strip()}"))
        elif ai_share.AI_MESSAGE.search(message):
            line = next((ln for ln in message.splitlines() if ai_share.AI_MESSAGE.search(ln)), "AI co-author")
            out.append((sha, line.strip()))
    return out


def _empty(section):
    """True when the section holds nothing but the template's HTML comment (or nothing at all)."""
    return not HTML_COMMENT.sub("", section or "").strip()


def ai_section(body):
    """The text of the pull request's "AI assistance" section, or None when it is missing."""
    match = re.search(r"^##\s*AI assistance\s*$(.*?)(?=^##\s|\Z)", body or "", re.M | re.S | re.I)
    return match.group(1).strip() if match else None


def assess(declared, section, score):
    """(level, message): level is 'declared', 'none-declared', 'check', 'unanswered' or 'ok'."""
    answered = section is not None and not _empty(section)
    says_no_ai = answered and NO_AI.search(section) and not re.search(r"\b(yes|claude|copilot|chatgpt|gpt|gemini|"
                                                                        r"cursor|codex|llm|assist)", section, re.I)
    if declared or (answered and not says_no_ai):
        return "declared", "AI assistance is declared."
    if score is not None and score >= 50:
        return "check", ("The added code shows many style signs of AI-written code, but no AI help is declared. "
                         "If an AI tool helped, please say so in the \"AI assistance\" section; if not, ignore this.")
    if not answered:
        return "unanswered", "Please fill in the \"AI assistance\" section of the pull request description."
    return "ok", "No AI help declared, and no strong style signs of it."


def report(declared, section, score, hits, level, message):
    lines = ["## AI assistance", "", f"**{message}**", ""]
    if declared:
        lines += ["Declared in commits:", ""] + [f"- `{sha}`: {how}" for sha, how in declared[:20]] + [""]
    if section is not None and not _empty(section):
        lines += ["Pull request says:", "", "> " + section.replace("\n", "\n> ")[:1500], ""]
    if score is None:
        lines.append("Style signals: too little added code to estimate.")
    else:
        lines.append(f"Style signals of AI-written code: **{score}/100** (an estimate, not proof).")
        if hits:
            lines += ["", "| Signal | Hits |", "|---|---|"] + [f"| {k} | {v} |" for k, v in hits.items()]
    text = "\n".join(lines) + "\n"
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    if level in ("check", "unanswered"):
        print(f"::warning title=AI assistance::{message}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--pr-body", help="file with the pull request description")
    parser.add_argument("--strict", action="store_true", help="fail when the AI section is unanswered or the "
                                                               "signals are strong without a declaration")
    parser.add_argument("--block-ai", action="store_true", help="fail when AI help is declared or the style "
                                                                 "score is 50 or more")
    args = parser.parse_args(argv)
    span = f"{args.base}...{args.head}"
    body = ""
    if args.pr_body and os.path.exists(args.pr_body):
        with open(args.pr_body, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    declared = declared_commits(span)
    section = ai_section(body)
    score, hits = style_score(added_code_lines(git("diff", "-U0", "--no-color", "--no-ext-diff", span)))
    level, message = assess(declared, section, score)
    report(declared, section, score, hits, level, message)
    if args.block_ai and level in ("declared", "check"):
        print("::error title=AI assistance::This pull request contains AI-assisted code"
              f"{' (declared)' if level == 'declared' else ' (style score ' + str(score) + '/100)'}; "
              "only code written without AI can be merged.")
        return 1
    return 1 if args.strict and level in ("check", "unanswered") else 0


if __name__ == "__main__":
    sys.exit(main())
