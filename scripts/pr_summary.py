# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Post one summary comment on a pull request: what it changes and whether it can be merged.

    python3 scripts/pr_summary.py HEAD_SHA          # find the open pull request for HEAD_SHA
    python3 scripts/pr_summary.py HEAD_SHA NUMBER   # or name it

Run by pr-summary.yml whenever one of the pull request workflows finishes. The comment
is created once and then updated, so each pull request has exactly one. It lists the
changed files by area, the result of every required check, other failed checks, merge
conflicts, and a short hint for the checks that fail most often. It reads only the
GitHub API (GITHUB_TOKEN, GITHUB_REPOSITORY) and never the pull request's code.
"""
import json
import os
import re
import sys
import urllib.request

MARKER = "<!-- fleetpilot-pr-summary -->"
BOT = "github-actions[bot]"
# The required status checks on main (Settings > Branches). Keep in sync by hand: the
# workflow token cannot read branch protection.
REQUIRED = ("pytest (Python 3.11)", "pytest (Python 3.12)", "pytest (Python 3.13)",
            "Analyze (python)", "Safe to merge", "AI assistance")
FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}
PASSED = {"success", "neutral", "skipped"}
# First match wins.
AREAS = (
    ("Workflows and CI", r"^\.github/"),
    ("Tests", r"^tests/|(^|/)test_[^/]*\.py$|(^|/)conftest\.py$"),
    ("Dependencies", r"(^|/)requirements[^/]*\.(txt|in)$|(^|/)package(-lock)?\.json$|\.gradle(\.kts)?$"),
    ("Android app", r"^FleetPilotAndroid/"),
    ("C# port", r"^FleetPilotCS/"),
    ("Home Assistant integration", r"^integrations/"),
    ("Plugins", r"^addons/"),
    ("Translations", r"^i18n\.py$|^easy_language\.py$|^locales?/"),
    ("Web pages", r"^templates/|^static/"),
    ("Install and update scripts", r"\.sh$|^deploy/|^proxmox/"),
    ("Developer scripts", r"^scripts/|^fuzz/|^demo/"),
    ("Documentation", r"\.md$|^docs/|\.pdf$"),
    ("App code", r"\.py$"),
)
HINTS = {
    "AI assistance": "The pull request declares AI help or looks AI-written (details in the job summary). "
                     "A maintainer can allow it anyway by commenting `/allow-ai {sha} <reason>`.",
    "Safe to merge": "Fails when *Change checks*, *Functional* or *Viruses and backdoors* fail; fix those first.",
    "Change checks": "Usually a missing `CHANGELOG.md` line under Unreleased, new interface text without a German "
                     "translation, or a ShellCheck warning. The job summary says which.",
    "Analyze (python)": "CodeQL found a possible security problem in the changed code; see the Security tab.",
}
PYTEST_HINT = ("Open the log: a failing test, the coverage floor, untested changed lines, or "
               "*Check dependencies for known vulnerabilities* (pip-audit, often not caused by the pull request).")


def area_of(path):
    for name, pattern in AREAS:
        if re.search(pattern, path):
            return name
    return "Other files"


def areas(files):
    """[(area, files, added, deleted)] sorted by changed lines, largest first."""
    out = {}
    for f in files:
        row = out.setdefault(area_of(f["filename"]), [0, 0, 0])
        row[0] += 1
        row[1] += f.get("additions", 0)
        row[2] += f.get("deletions", 0)
    return sorted(((a, *v) for a, v in out.items()), key=lambda r: (-(r[2] + r[3]), r[0]))


def latest_checks(check_runs):
    """{name: check run}, keeping only the newest run of each name (re-runs replace older ones)."""
    out = {}
    for run in sorted(check_runs, key=lambda r: r.get("id", 0)):
        out[run["name"]] = run
    return out


def state(run):
    if run is None:
        return "missing"
    if run.get("status") != "completed":
        return "running"
    if run.get("conclusion") in PASSED:
        return "passed"
    return "failed" if run.get("conclusion") in FAILED else "running"


def verdict(pr, checks):
    """(level, headline, reasons); level is "ready", "waiting" or "blocked"."""
    reasons = []
    failed = [n for n in REQUIRED if state(checks.get(n)) == "failed"]
    pending = [n for n in REQUIRED if state(checks.get(n)) in ("running", "missing")]
    if failed:
        reasons.append("Required checks failed: " + ", ".join(f"*{n}*" for n in failed) + ".")
    if pr.get("mergeable") is False:
        reasons.append("It has merge conflicts with `{}`; update the branch.".format(pr["base"]["ref"]))
    if pr.get("draft"):
        reasons.append("It is still a draft.")
    if reasons:
        return "blocked", "Not ready to merge", reasons
    if pending:
        return "waiting", "Waiting for checks", ["Still running: " + ", ".join(f"*{n}*" for n in pending) + "."]
    return "ready", "Ready to merge", ["All required checks passed and there are no merge conflicts. "
                                       "A maintainer still reviews the change before merging."]


def _link(run, text):
    url = (run or {}).get("details_url") or (run or {}).get("html_url")
    return f"[{text}]({url})" if url else text


def render(pr, files, check_runs):
    checks = latest_checks(check_runs)
    level, headline, reasons = verdict(pr, checks)
    icon = {"ready": ":green_circle:", "waiting": ":yellow_circle:", "blocked": ":red_circle:"}[level]
    sha = pr["head"]["sha"]
    added = sum(f.get("additions", 0) for f in files)
    deleted = sum(f.get("deletions", 0) for f in files)
    lines = [MARKER, f"## {icon} {headline}", ""] + [f"- {r}" for r in reasons] + [
        "", f"Commit `{sha[:7]}`; updated whenever a check finishes.", "",
        "### What this pull request changes", "",
        f"{len(files)} files, +{added} / -{deleted} lines.", "",
        "| Area | Files | Added | Deleted |", "|---|---:|---:|---:|"]
    lines += [f"| {a} | {n} | +{ad} | -{de} |" for a, n, ad, de in areas(files)]
    lines += ["", "<details><summary>Changed files</summary>", ""]
    lines += [f"- `{f['filename']}` ({f.get('status', 'modified')}, +{f.get('additions', 0)} / "
              f"-{f.get('deletions', 0)})" for f in files[:300]]
    if len(files) > 300:
        lines.append(f"- ... and {len(files) - 300} more")
    lines += ["", "</details>", "", "### Required checks", "", "| Check | Result |", "|---|---|"]
    label = {"passed": ":white_check_mark: passed", "failed": ":x: failed", "running": ":hourglass: running",
             "missing": ":hourglass: not started"}
    for name in REQUIRED:
        run = checks.get(name)
        lines.append(f"| {_link(run, name)} | {label[state(run)]} |")
    other_failed = sorted(n for n, r in checks.items() if n not in REQUIRED and state(r) == "failed")
    other_running = sum(1 for n, r in checks.items() if n not in REQUIRED and state(r) == "running")
    other_passed = sum(1 for n, r in checks.items() if n not in REQUIRED and state(r) == "passed")
    lines += ["", f"Other checks: {other_passed} passed, {len(other_failed)} failed, {other_running} running."]
    if other_failed:
        lines += ["", "Failed, not required:"] + [f"- {_link(checks[n], n)}" for n in other_failed]
    hints = {}
    for name in [n for n in REQUIRED if state(checks.get(n)) == "failed"] + other_failed:
        key = "pytest" if name.startswith("pytest") else name
        hint = PYTEST_HINT if key == "pytest" else HINTS.get(name)
        if hint and key not in hints:
            hints[key] = hint.format(sha=sha[:7])
    if hints:
        lines += ["", "### How to fix", ""] + [f"- **{k}:** {h}" for k, h in hints.items()]
    return "\n".join(lines) + "\n"


class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def call(self, method, path, body=None):
        url = path if path.startswith("https://") else f"https://api.github.com/repos/{self.repo}/{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            **({"Content-Type": "application/json"} if data else {})})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def pages(self, path, key=None):
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while True:
            batch = self.call("GET", f"{path}{sep}per_page=100&page={page}")
            batch = batch[key] if key else batch
            out += batch
            if len(batch) < 100:
                return out
            page += 1


def find_pr(gh, head_sha):
    for pr in gh.pages("pulls?state=open"):
        if pr["head"]["sha"] == head_sha:
            return pr["number"]
    return None


def post(gh, number, body):
    """Update this script's earlier comment on the pull request, or create the first one."""
    for comment in gh.pages(f"issues/{number}/comments"):
        if (comment.get("user") or {}).get("login") == BOT and (comment.get("body") or "").startswith(MARKER):
            if comment["body"] != body:
                gh.call("PATCH", f"issues/comments/{comment['id']}", {"body": body})
            return "updated"
    gh.call("POST", f"issues/{number}/comments", {"body": body})
    return "created"


def main(argv=None, gh=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2):
        sys.exit(__doc__)
    gh = gh or GitHub(os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_TOKEN", ""))
    head_sha = argv[0]
    number = int(argv[1]) if len(argv) == 2 else find_pr(gh, head_sha)
    if number is None:
        print(f"No open pull request has head commit {head_sha}; nothing to do.")
        return 0
    pr = gh.call("GET", f"pulls/{number}")
    if pr["head"]["sha"] != head_sha:
        print(f"Pull request #{number} has moved on to {pr['head']['sha'][:7]}; a newer run will update it.")
        return 0
    files = gh.pages(f"pulls/{number}/files")
    runs = gh.pages(f"commits/{head_sha}/check-runs", key="check_runs")
    print(f"Summary comment {post(gh, number, render(pr, files, runs))} on #{number}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
