# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for two_factor backup codes: generation, use and storage."""
import re
import sqlite3

import pytest

CODE_RE = re.compile(r"^[0-9A-F]{4}-[0-9A-F]{4}$")


@pytest.fixture
def tfa(tmp_path, monkeypatch):
    import two_factor

    monkeypatch.setattr(two_factor, "TFA_DB", tmp_path / "2fa.db")
    two_factor.init_db()
    return two_factor


def test_regenerate_returns_ten_different_codes_in_format(tfa):
    codes = tfa.regenerate_backup_codes(1)

    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(CODE_RE.match(code) for code in codes)
    assert tfa.get_backup_codes(1) == 10


def test_a_code_works_once_and_the_count_drops(tfa):
    codes = tfa.regenerate_backup_codes(1)

    assert tfa.verify_backup_code(1, codes[0]) is True
    assert tfa.get_backup_codes(1) == 9
    assert tfa.verify_backup_code(1, codes[0]) is False
    assert tfa.get_backup_codes(1) == 9


def test_dashes_spaces_and_case_do_not_matter(tfa):
    codes = tfa.regenerate_backup_codes(1)

    assert tfa.verify_backup_code(1, codes[0].lower()) is True
    assert tfa.verify_backup_code(1, codes[1].replace("-", "")) is True
    assert tfa.verify_backup_code(1, codes[2].replace("-", " ")) is True
    assert tfa.verify_backup_code(1, codes[3].replace("-", "").lower()) is True


def test_a_code_of_user_1_does_not_work_for_user_2(tfa):
    codes = tfa.regenerate_backup_codes(1)
    tfa.regenerate_backup_codes(2)

    assert tfa.verify_backup_code(2, codes[0]) is False
    assert tfa.verify_backup_code(1, codes[0]) is True


def test_regenerating_makes_all_old_codes_invalid(tfa):
    old_codes = tfa.regenerate_backup_codes(1)
    new_codes = tfa.regenerate_backup_codes(1)

    assert tfa.get_backup_codes(1) == 10
    for code in old_codes:
        assert tfa.verify_backup_code(1, code) is False
    assert tfa.verify_backup_code(1, new_codes[0]) is True


def test_the_database_stores_only_hashes(tfa, tmp_path):
    codes = tfa.regenerate_backup_codes(1)

    conn = sqlite3.connect(str(tmp_path / "2fa.db"))
    try:
        stored = [row[0] for row in conn.execute("SELECT code_hash FROM backup_codes")]
    finally:
        conn.close()

    assert len(stored) == 10
    for code in codes:
        assert code not in stored
        assert code.replace("-", "") not in stored
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in stored)
