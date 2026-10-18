# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Look for backdoors and malicious code in the lines a pull request adds.

    python3 scripts/pr_threat_scan.py BASE_SHA HEAD_SHA     # lines a pull request adds
    python3 scripts/pr_threat_scan.py --all                  # every tracked file (regular scan)

Run by .github/workflows/pr-check.yml, always in the version from the base branch,
so a pull request cannot switch it off by editing it. Viruses in files are ClamAV's
job (same workflow); this script reads the diff for things a virus scanner misses:
reverse shells, obfuscated code that is run, downloads piped into a shell, crypto
miners, hidden Unicode that changes how code reads (Trojan Source), embedded SSH
keys, new binaries and scripts inside SVG images.

Findings marked "high" fail the check. "review" findings only list what a person
should look at closely (CI, installer and sign-in code, dependencies, ...).
A finding is a reason to read the change, not proof of bad intent.
"""
import os
import re
import subprocess
import sys

CODE = re.compile(r"\.(py|sh|bash|js|ts|kt|kts|cs|ps1|psm1|yml|yaml|html|j2|service|conf|toml|ini|cfg|bat|cmd)$"
                  r"|(^|/)(Dockerfile|Makefile)$|^scripts/fleetpilot-")
# This scanner and its tests contain the patterns on purpose.
SELF = re.compile(r"(^|/)(pr_threat_scan\.py|test_pr_threat_scan\.py)$")

# (rule id, regex, applies to code files only, what it means)
HIGH_RULES = [
    ("reverse-shell", re.compile(r"/dev/(tcp|udp)/|\bnc(at)?\b[^\n]*\s-[ec]\s|bash\s+-i\s*>&|socat\b[^\n]*exec:|"
                                 r"pty\.spawn\(|socket\.socket\([^\n]*\)[^\n]*(dup2|subprocess)", re.I), True,
     "looks like a reverse shell"),
    ("obfuscated-exec", re.compile(r"(?<![.\w])(exec|eval|compile)\s*\([^\n]*(b64decode|a85decode|b32decode|decompress|"
                                   r"marshal\.loads|codecs\.decode|bytes\.fromhex|fromCharCode|\\x[0-9a-f]{2})", re.I),
     True, "runs decoded or obfuscated code"),
    ("powershell-encoded", re.compile(r"powershell[^\n]*\s-(e|enc|encodedcommand)\s+[A-Za-z0-9+/=]{40,}", re.I), True,
     "runs a hidden PowerShell command"),
    ("download-and-run", re.compile(r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b|"
                                    r"Invoke-Expression[^\n]*(DownloadString|Invoke-WebRequest|iwr)|\biex\s*\(",
                                    re.I), True, "downloads code and runs it"),
    ("crypto-miner", re.compile(r"xmrig|stratum\+(tcp|ssl)://|\bminerd\b|cryptonight|coinhive|nicehash", re.I), False,
     "crypto-mining software"),
    ("exfiltration-host", re.compile(r"pastebin\.com|transfer\.sh|ngrok\.(io|app)|discord(app)?\.com/api/webhooks|"
                                     r"api\.telegram\.org/bot|requestbin|webhook\.site|interact\.sh|burpcollaborator",
                                     re.I), True, "sends data to a paste, tunnel or webhook service"),
    ("ssh-key", re.compile(r"(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp\d+) AAAA[0-9A-Za-z+/]{40,}"), True,
     "adds a literal SSH public key (could grant someone access)"),
    ("private-key", re.compile(r"-----BEGIN ((RSA|EC|DSA|OPENSSH|PGP) )?PRIVATE KEY-----"
                                   r"(\s*$|(\\n)?[A-Za-z0-9+/]{20,})"), False,
     "adds a private key"),
    ("ssh-root-login", re.compile(r"PermitRootLogin\s+yes|PasswordAuthentication\s+yes", re.I), True,
     "weakens SSH server settings"),
    ("persistence", re.compile(r"(crontab\s+-|/etc/cron\.|/etc/rc\.local|\.bashrc|\.profile|/etc/ld\.so\.preload)"
                               r"[^\n]*(>>|\s>\s|\btee\b|\.write\(|open\([^)]*['\"][aw])", re.I), True,
     "writes to a startup file or cron"),
]
# Not blocking, but a person should look: FleetPilot installs SSH keys on purpose.
REVIEW_RULES = [
    ("authorized-keys", re.compile(r"authorized_keys[^\n]*(>>|\s>\s|\btee\b|\.write\(|open\([^)]*['\"][aw])|"
                                   r"(>>|\btee\b)[^\n]*authorized_keys", re.I), "writes to authorized_keys"),
]
TESTS = re.compile(r"(^|/)(test_[^/]*|tests/.*|conftest)\.py$")
DOCS = re.compile(r"\.(md|html|j2|txt|rst)$", re.I)
COMMENT = re.compile(r"^\s*(#|//|<!--|\*|::|rem\s)", re.I)
# Rules that are expected in docs (install commands shown to users) or in tests (sample keys).
NOT_IN_DOCS = {"download-and-run"}
REVIEW_IN_TESTS = {"ssh-key"}
# Trojan Source (CVE-2021-42574) and invisible characters.
HIDDEN_UNICODE = re.compile("[‪-‮⁦-⁩​-‍⁠﻿]")
LONG_BLOB = re.compile(r"[A-Za-z0-9+/]{400,}={0,2}")
SVG_SCRIPT = re.compile(r"<script|\bon(load|error|click|mouseover)\s*=|javascript:", re.I)

BINARY_OK = re.compile(r"\.(png|jpe?g|gif|webp|ico|pdf|woff2?|ttf|otf)$", re.I)
SENSITIVE = [
    (re.compile(r"^\.github/"), "CI workflows and repository settings"),
    (re.compile(r"^(install[^/]*\.sh|update\.sh|reset-password\.sh|remote-access\.sh)$|^proxmox/|^deploy/|"
                r"^scripts/fleetpilot-"), "installer, updater or privileged helper"),
    (re.compile(r"(^|/)(privileged|ssh_helper|secret_box|account_security|two_factor|user_management|"
                r"runtime_env|updater|safe_errors)\.py$"), "sign-in, secrets, SSH or privileged code"),
    (re.compile(r"(^|/)requirements[^/]*\.(txt|in)$|(^|/)libs\.versions\.toml$|(^|/)build\.gradle\.kts$"),
     "dependencies"),
    (re.compile(r"^\.clusterfuzzlite/|^fuzz/"), "fuzzing setup"),
    (SELF, "this scanner itself"),
]


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, errors="replace").stdout


def added_lines(diff_text):
    """Yield (path, line number, text) for every added line of a unified diff (-U0)."""
    path, line = None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            line = int(match.group(1)) if match else 0
        elif raw.startswith("+") and path:
            yield path, line, raw[1:]
            line += 1


def scan_lines(lines):
    """Return findings [(severity, rule, path, line, message)] for added lines."""
    findings = []
    for path, number, text in lines:
        if SELF.search(path):
            continue
        is_code = bool(CODE.search(path))
        for rule, regex, code_only, meaning in HIGH_RULES:
            if not (is_code or not code_only) or not regex.search(text):
                continue
            if rule in NOT_IN_DOCS and (DOCS.search(path) or COMMENT.match(text)):
                continue
            severity = "review" if rule in REVIEW_IN_TESTS and TESTS.search(path) else "high"
            findings.append((severity, rule, path, number, meaning))
        for rule, regex, meaning in REVIEW_RULES:
            if is_code and regex.search(text):
                findings.append(("review", rule, path, number, meaning))
        if is_code and HIDDEN_UNICODE.search(text):
            findings.append(("high", "hidden-unicode", path, number,
                             "invisible or text-direction Unicode characters (code may not do what it shows)"))
        if is_code and LONG_BLOB.search(text):
            findings.append(("review", "encoded-blob", path, number, "long encoded string; check what it contains"))
        if path.lower().endswith(".svg") and SVG_SCRIPT.search(text):
            findings.append(("high", "svg-script", path, number, "script or event handler inside an SVG image"))
    return findings


def scan_files(numstat, name_status):
    """Findings about whole files: new binaries and sensitive paths."""
    findings = []
    for row in numstat.splitlines():
        parts = row.split("\t")
        if len(parts) == 3 and parts[0] == "-" and not BINARY_OK.search(parts[2]):
            findings.append(("high", "binary", parts[2], 0,
                             "adds or changes a binary file (executables, archives and APKs belong in releases)"))
    for row in name_status.splitlines():
        parts = row.split("\t")
        if len(parts) < 2:
            continue
        path = parts[-1]
        if parts[0].startswith(("A", "M", "R", "C")) and os.path.basename(path).startswith(".") \
                and path.endswith((".sh", ".py")):
            findings.append(("review", "hidden-file", path, 0, "hidden script file"))
        for regex, area in SENSITIVE:
            if regex.search(path):
                findings.append(("review", "sensitive-path", path, 0, f"changes {area}"))
                break
    return findings


def report(findings, title="Backdoor and malware check"):
    """Print GitHub annotations and a summary; return the exit code."""
    high = [f for f in findings if f[0] == "high"]
    for severity, rule, path, line, message in findings:
        kind = "error" if severity == "high" else "warning"
        where = f"file={path},line={line}" if line else f"file={path}"
        print(f"::{kind} {where},title={rule}::{message}")
    summary = [f"## {title}", ""]
    if not findings:
        summary.append("No suspicious changes found.")
    else:
        summary += ["| | Rule | File | Why |", "|---|---|---|---|"]
        for severity, rule, path, line, message in findings:
            mark = "❌" if severity == "high" else "👀"
            summary.append(f"| {mark} | `{rule}` | `{path}{f':{line}' if line else ''}` | {message} |")
        summary += ["", f"{len(high)} blocking, {len(findings) - len(high)} to review by a person."]
    text = "\n".join(summary) + "\n"
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 1 if high else 0


def all_tracked_lines():
    """Every line of every tracked text file, for the regular full scan; binaries as findings."""
    findings, lines = [], []
    for path in git("ls-files", "-z").split("\0"):
        if not path or not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        if b"\0" in data[:8192]:
            if not BINARY_OK.search(path):
                findings.append(("high", "binary", path, 0, "binary file in the repository"))
            continue
        lines += [(path, n, text) for n, text in enumerate(data.decode("utf-8", "replace").splitlines(), 1)]
    return lines, findings


def main(argv):
    if argv[1:] == ["--all"]:
        lines, findings = all_tracked_lines()
        return report(scan_lines(lines) + findings, title="Backdoor and malware check (whole repository)")
    if len(argv) != 3:
        sys.exit(__doc__)
    span = f"{argv[1]}...{argv[2]}"
    findings = scan_lines(added_lines(git("diff", "-U0", "--no-color", "--no-ext-diff", span)))
    findings += scan_files(git("diff", "--numstat", span), git("diff", "--name-status", span))
    return report(findings)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
