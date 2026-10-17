# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""send_email picks implicit TLS for port 465, STARTTLS otherwise, and always closes the connection."""
import smtplib

import pytest

import email_notifier


class FakeSMTP:
    """Records how send_email used the connection instead of talking to a server."""

    instances = []
    fail_send = False

    def __init__(self, host, port, **kwargs):
        self.host, self.port, self.kwargs = host, port, kwargs
        self.calls = []
        self.closed = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def starttls(self, **kwargs):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, msg):
        self.calls.append("send_message")
        if FakeSMTP.fail_send:
            raise smtplib.SMTPException("boom")


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_send = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)

    def configure(port, **extra):
        settings = {
            "email_enabled": True,
            "smtp_server": "mail.example.com",
            "smtp_port": port,
            "sender_email": "fleet@example.com",
            "recipient_emails": ["admin@example.com"],
            "smtp_username": "user",
            "smtp_password": "secret",
            **extra,
        }
        monkeypatch.setattr(email_notifier.email_config, "load_email_settings", lambda: settings)

    return configure


def test_port_465_uses_implicit_tls_without_starttls(smtp):
    smtp(465)
    assert email_notifier.send_email("s", "b") == (True, None)
    (server,) = FakeSMTP.instances
    assert type(server) is FakeSMTPSSL
    assert "starttls" not in server.calls
    assert server.calls == ["login", "send_message"]
    assert server.kwargs["context"] is not None


def test_port_587_uses_starttls(smtp):
    smtp(587)
    assert email_notifier.send_email("s", "b") == (True, None)
    (server,) = FakeSMTP.instances
    assert type(server) is FakeSMTP
    assert server.calls == ["starttls", "login", "send_message"]


def test_plain_smtp_when_tls_disabled(smtp):
    smtp(25, smtp_use_tls=False)
    assert email_notifier.send_email("s", "b") == (True, None)
    assert FakeSMTP.instances[0].calls == ["login", "send_message"]


@pytest.mark.parametrize("port", [465, 587, "587"])
def test_timeout_is_always_passed(smtp, port):
    smtp(port)
    email_notifier.send_email("s", "b")
    (server,) = FakeSMTP.instances
    assert server.kwargs["timeout"] == email_notifier.SMTP_TIMEOUT
    assert server.port == int(port)


@pytest.mark.parametrize("port", [465, 587])
def test_connection_closed_when_send_fails(smtp, port):
    smtp(port)
    FakeSMTP.fail_send = True
    ok, error = email_notifier.send_email("s", "b")
    assert not ok
    assert "boom" in error
    assert FakeSMTP.instances[0].closed
