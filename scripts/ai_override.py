# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find a maintainer's override for the AI assistance check on a pull request.

    python3 scripts/ai_override.py PR_NUMBER HEAD_SHA PR_AUTHOR

The AI assistance check (scripts/ai_detect.py --block-ai) is required for merging.
A maintainer can still let one specific pull request through by commenting on it:

    /allow-ai <commit> <reason>

for example "/allow-ai d6b1f82 release PR, reviewed line by line". The override counts
only when:

- the comment's author is the repository owner, a member or a collaborator; members
  and collaborators cannot allow their own pull requests, the owner can (nobody else
  could approve the owner's pull requests);
- <commit> is the pull request's current head commit (at least 7 characters of its
  SHA), so new pushes need a new approval;
- a reason follows the commit.

Exits 0 and prints who allowed it and why when such a comment exists, 1 otherwise.
Reads the comments through the GitHub API (GITHUB_TOKEN, GITHUB_REPOSITORY).
"""
import json
import os
import re
import sys
import urllib.request

COMMAND = re.compile(r"^\s*/allow-ai\s+([0-9a-f]{7,40})\s+(\S.{2,})$", re.I | re.M)
ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}


def find_override(comments, head_sha, pr_author):
    """The (login, reason, url) of the newest valid override among ``comments``, or None."""
    for comment in reversed(comments):
        login = (comment.get("user") or {}).get("login", "")
        association = comment.get("author_association")
        if association not in ALLOWED or not login or (login == pr_author and association != "OWNER"):
            continue
        for sha, reason in COMMAND.findall(comment.get("body") or ""):
            if head_sha.lower().startswith(sha.lower()):
                return login, reason.strip()[:300], comment.get("html_url", "")
    return None


def fetch_comments(repo, number, token):
    comments, page = [], 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues/{number}/comments?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        comments += batch
        if len(batch) < 100:
            return comments
        page += 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        sys.exit(__doc__)
    number, head_sha, author = argv
    found = find_override(fetch_comments(os.environ["GITHUB_REPOSITORY"], number, os.environ.get("GITHUB_TOKEN", "")),
                          head_sha, author)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if found:
        login, reason, url = found
        text = (f"## AI assistance: allowed by a maintainer\n\n**@{login}** allowed this pull request "
                f"(commit `{head_sha[:7]}`): {reason}\n\n{url}\n")
        print(f"::notice title=AI assistance::Allowed by @{login} for {head_sha[:7]}: {reason}")
        code = 0
    else:
        text = ("\nA maintainer can allow this pull request anyway by commenting:\n\n"
                f"    /allow-ai {head_sha[:7]} <reason>\n\n"
                "The approval counts only for this commit; new pushes need a new one.\n")
        code = 1
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
