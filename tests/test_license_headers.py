# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every source file states its copyright holder and license (SPDX), near the top."""
import pathlib
import subprocess

import pytest

# Third-party code keeps its own license; the community-scripts files carry that project's MIT header.
SKIP = ("static/vendor/", "proxmox/community-scripts/", "docs/")
SOURCE = (".py", ".sh", ".js", ".css", ".html", ".cs", ".kt", ".kts", ".yml", ".yaml", ".conf", ".service",
          ".toml", ".ini", ".in", ".properties", ".csproj", ".xml")


def _source_files():
    try:
        tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [f for f in tracked if not f.startswith(SKIP)
            and (f.endswith(SOURCE) or f.startswith("scripts/fleetpilot-") or f.endswith("Dockerfile"))]


def test_every_source_file_has_an_spdx_header():
    root = pathlib.Path(__file__).resolve().parent.parent
    missing = []
    for path in _source_files():
        head = (root / path).read_text(encoding="utf-8")[:600]
        if ("SPDX-License-Identifier: GPL-3.0-or-later" not in head
                or "SPDX-FileCopyrightText: Copyright the FleetPilot contributors" not in head):
            missing.append(path)
    assert not missing, "Add the two SPDX lines (see CONTRIBUTING.md) to:\n" + "\n".join(missing)
