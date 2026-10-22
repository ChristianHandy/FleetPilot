# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""requirements-lock.txt (what installs get) must satisfy requirements.txt (what FleetPilot needs)."""
import os
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pins(path):
    with open(os.path.join(HERE, path), encoding="utf-8") as fh:
        return {canonicalize_name(m.group(1)): m.group(2)
                for m in re.finditer(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)", fh.read(), re.M)}


def test_lock_satisfies_requirements():
    pins = _pins("requirements-lock.txt")
    with open(os.path.join(HERE, "requirements.txt"), encoding="utf-8") as fh:
        wanted = [Requirement(line) for line in (raw.split("#")[0].strip() for raw in fh) if line]
    problems = [f"{req} (lock has {pins.get(canonicalize_name(req.name), 'nothing')})"
                for req in wanted if not req.specifier.contains(pins.get(canonicalize_name(req.name), "0"), prereleases=True)]
    assert not problems, ("Regenerate the lock (see its first lines): " + ", ".join(problems))


def test_every_pin_has_a_hash():
    with open(os.path.join(HERE, "requirements-lock.txt"), encoding="utf-8") as fh:
        blocks = re.split(r"\n(?=[A-Za-z0-9])", fh.read())
    assert all("--hash=sha256:" in b for b in blocks if "==" in b)
