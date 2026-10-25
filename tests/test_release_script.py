# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/release.py, which prepares beta, main, patch and hotfix releases."""
import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location("release",
                                               pathlib.Path(__file__).resolve().parent.parent / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Fixed

- Something.

## [1.8.0] — 2026-10-18

Old notes.
"""


@pytest.mark.parametrize("kind,current,expected", [
    ("beta", "1.8.0", "1.9.0-beta.1"),
    ("beta", "1.9.0-beta.1", "1.9.0-beta.2"),
    ("release", "1.9.0-beta.2", "1.9.0"),
    ("release", "1.8.0", "1.9.0"),
    ("major", "1.9.0", "2.0.0"),
    ("patch", "1.8.0", "1.8.1"),
    ("hotfix", "1.8.1", "1.8.2"),
])
def test_next_version(kind, current, expected):
    assert release.next_version(kind, current) == expected


def test_patch_and_hotfix_refuse_a_beta_and_unknown_input():
    for kind in ("patch", "hotfix"):
        with pytest.raises(release.ReleaseError, match="beta"):
            release.next_version(kind, "1.9.0-beta.1")
    with pytest.raises(release.ReleaseError, match="unknown kind"):
        release.next_version("nightly", "1.8.0")
    with pytest.raises(release.ReleaseError, match="not a version"):
        release.parse("1.8")


def test_stable_base_is_the_newest_stable_tag():
    tags = ["v1.7.0", "v1.10.0-beta.1", "v1.8.0", "v1.9.0", "v1.8.1", "latest"]
    assert release.stable_base(tags) == "v1.9.0"
    with pytest.raises(release.ReleaseError):
        release.stable_base(["v2.0.0-beta.1"])


def test_close_changelog_moves_unreleased_into_the_new_section():
    text = release.close_changelog(CHANGELOG, "1.8.1", "2026-10-25")
    assert "## [Unreleased]\n\n## [1.8.1] — 2026-10-25\n\n### Fixed\n\n- Something.\n\n## [1.8.0]" in text
    with pytest.raises(release.ReleaseError, match="nothing under Unreleased"):
        release.close_changelog(text, "1.8.2", "2026-10-26")
    with pytest.raises(release.ReleaseError, match="already has"):
        release.close_changelog(CHANGELOG, "1.8.0", "2026-10-25")
    with pytest.raises(release.ReleaseError, match="no '## \\[Unreleased\\]'"):
        release.close_changelog("# Changelog\n", "1.8.1", "2026-10-25")


def _project(tmp_path):
    (tmp_path / "fleetpilot_version.py").write_text('VERSION = "1.8.0"\nTAG = f"v{VERSION}"\n')
    gradle = tmp_path / "FleetPilotAndroid" / "app" / "build.gradle.kts"
    gradle.parent.mkdir(parents=True)
    gradle.write_text('android {\n    defaultConfig {\n        versionCode = 18\n        versionName = "1.8.0"\n    }\n}\n')
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    return gradle


def test_apply_writes_every_version_and_the_changelog(tmp_path):
    gradle = _project(tmp_path)
    assert release.apply("1.8.1", tmp_path, "2026-10-25") == "1.8.0"
    assert release.current_version(tmp_path) == "1.8.1"
    assert 'versionCode = 19\n        versionName = "1.8.1"' in gradle.read_text()
    assert "## [1.8.1] — 2026-10-25" in (tmp_path / "CHANGELOG.md").read_text()
    with pytest.raises(release.ReleaseError, match="already is"):
        release.apply("1.8.1", tmp_path)


def test_main(monkeypatch, capsys):
    monkeypatch.setattr(release, "current_version", lambda root=None: "1.8.0")
    assert release.main(["next", "patch"]) == 0
    assert capsys.readouterr().out == "1.8.1\n"
    assert release.main(["next", "nightly"]) == 1
    assert "::error title=Release::unknown kind" in capsys.readouterr().out
    monkeypatch.setattr(release.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "v1.8.0\nv1.9.0-beta.1\nv1.7.0\n"})())
    assert release.main(["stable-base"]) == 0
    assert capsys.readouterr().out == "v1.8.0\n"
    with pytest.raises(SystemExit):
        release.main(["what"])


def test_the_repository_versions_agree():
    root = pathlib.Path(release.ROOT)
    version = release.current_version(root)
    release.parse(version)
    gradle = (root / "FleetPilotAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert f'versionName = "{version}"' in gradle
    assert f"## [{version}]" in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_apply_updates_the_pinned_version_test_of_old_release_branches(tmp_path):
    _project(tmp_path)
    test = tmp_path / "test_production_hardening.py"
    test.write_text("assert r['version'] == '1.8.0'\nassert r['tag'] == 'v1.8.0'\n"
                    "assert r['display_name'] == 'FleetPilot v1.8.0'\n")
    release.apply("1.8.1", tmp_path, "2026-10-25")
    assert test.read_text() == ("assert r['version'] == '1.8.1'\nassert r['tag'] == 'v1.8.1'\n"
                                "assert r['display_name'] == 'FleetPilot v1.8.1'\n")


def test_apply_changes_nothing_when_a_file_is_missing(tmp_path):
    gradle = _project(tmp_path)
    gradle.unlink()
    with pytest.raises(release.ReleaseError, match="missing: FleetPilotAndroid"):
        release.apply("1.8.1", tmp_path)
    assert (tmp_path / "CHANGELOG.md").read_text() == CHANGELOG
    assert release.current_version(tmp_path) == "1.8.0"
