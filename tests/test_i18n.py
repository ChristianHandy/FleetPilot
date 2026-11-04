# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for browser language selection."""

import app as fp

def test_browser_language_german():
    client = fp.app.test_client()
    response = client.get(
        "/",
        headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
    )
    assert response.status_code == 200
    assert 'lang="de"' in response.get_data(as_text=True)


def test_browser_language_french():
    client = fp.app.test_client()
    response = client.get("/", headers={"Accept-Language": "fr"})
    assert 'lang="fr"' in response.get_data(as_text=True)


def test_unsupported_browser_language_falls_to_english():
    client = fp.app.test_client()
    response = client.get("/", headers={"Accept-Language": "ko"})
    assert 'lang="en"' in response.get_data(as_text=True)


def test_browser_language_is_not_persisted():
    client = fp.app.test_client()
    client.get("/", headers={"Accept-Language": "de"})

    with client.session_transaction() as session:
        assert "lang" not in session


def test_explicit_session_language_overrides_browser():
    client = fp.app.test_client()

    with client.session_transaction() as session:
        session["lang"] = "en"

    response = client.get(
        "/",
        headers={"Accept-Language": "de-DE,de;q=0.9"},
    )
    assert 'lang="en"' in response.get_data(as_text=True)

def test_set_language_overrides_browser():
    client = fp.app.test_client()

    client.get("/set_language?lang=en")

    response = client.get(
        "/",
        headers={"Accept-Language": "de-DE,de;q=0.9"},
    )

    assert 'lang="en"' in response.get_data(as_text=True)
