# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for email_notifier SMTP, SMTPS (port 465), timeouts, and cleanup."""
import smtplib
import ssl

import email_config
import email_notifier


def _make_recorder(raise_on_send=None):
    events = []

    class FakeSMTPBase:
        kind = "SMTP"

        def __init__(self, host, port, timeout=None, context=None):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.context = context
            self.starttls_called = False
            self.starttls_context = None
            self.logged_in = None
            self.sent_messages = []
            self.closed = False
            events.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.closed = True
            return False

        def starttls(self, context=None):
            self.starttls_called = True
            self.starttls_context = context

        def login(self, username, password):
            self.logged_in = (username, password)

        def send_message(self, msg):
            if raise_on_send is not None:
                raise raise_on_send
            self.sent_messages.append(msg)

        def quit(self):
            self.closed = True

    class FakeSMTP(FakeSMTPBase):
        kind = "SMTP"

    class FakeSMTP_SSL(FakeSMTPBase):
        kind = "SMTP_SSL"

    return events, FakeSMTP, FakeSMTP_SSL


def _patch_settings(monkeypatch, **overrides):
    settings = {
        "email_enabled": True,
        "smtp_server": "mail.example.test",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "smtp_username": "alerts@example.test",
        "smtp_password": "secret-password",
        "sender_email": "alerts@example.test",
        "recipient_emails": ["admin@example.test"],
    }
    settings.update(overrides)
    monkeypatch.setattr(email_config, "load_email_settings", lambda: dict(settings))


def test_port_465_uses_smtp_ssl_without_starttls(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, smtp_port=465, smtp_use_tls=True)

    ok, err = email_notifier.send_email("Test Subject", "Plain body", "<p>HTML</p>")

    assert ok is True
    assert err is None
    assert len(events) == 1
    conn = events[0]
    assert conn.kind == "SMTP_SSL"
    assert conn.host == "mail.example.test"
    assert conn.port == 465
    assert conn.timeout == email_notifier.SMTP_TIMEOUT
    assert conn.timeout is not None and conn.timeout > 0
    assert isinstance(conn.context, ssl.SSLContext)
    assert conn.starttls_called is False
    assert conn.logged_in == ("alerts@example.test", "secret-password")
    assert len(conn.sent_messages) == 1
    assert conn.closed is True


def test_port_587_uses_smtp_with_starttls_and_timeout(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, smtp_port=587, smtp_use_tls=True)

    ok, err = email_notifier.send_email("Subject 587", "Body 587")

    assert ok is True
    assert err is None
    assert len(events) == 1
    conn = events[0]
    assert conn.kind == "SMTP"
    assert conn.host == "mail.example.test"
    assert conn.port == 587
    assert conn.timeout == email_notifier.SMTP_TIMEOUT
    assert conn.timeout is not None and conn.timeout > 0
    assert conn.starttls_called is True
    assert isinstance(conn.starttls_context, ssl.SSLContext)
    assert len(conn.sent_messages) == 1
    assert conn.closed is True


def test_port_25_unencrypted_skips_starttls_with_timeout(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, smtp_port=25, smtp_use_tls=False, smtp_username="", smtp_password="")

    ok, err = email_notifier.send_email("Subject 25", "Body 25")

    assert ok is True
    assert err is None
    assert len(events) == 1
    conn = events[0]
    assert conn.kind == "SMTP"
    assert conn.port == 25
    assert conn.timeout == email_notifier.SMTP_TIMEOUT
    assert conn.starttls_called is False
    assert conn.logged_in is None
    assert conn.closed is True


def test_connection_closed_when_send_message_raises(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder(
        raise_on_send=smtplib.SMTPException("temporary server error")
    )
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)

    for port in (587, 465):
        _patch_settings(monkeypatch, smtp_port=port)
        ok, err = email_notifier.send_email("Failure Subject", "Body")
        assert ok is False
        assert "temporary server error" in err

    assert len(events) == 2
    assert events[0].kind == "SMTP"
    assert events[0].closed is True
    assert events[1].kind == "SMTP_SSL"
    assert events[1].closed is True


def test_connection_closed_on_auth_and_unexpected_errors(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder(
        raise_on_send=smtplib.SMTPAuthenticationError(535, b"auth failed")
    )
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, smtp_port=587)

    ok, err = email_notifier.send_email("Auth Fail", "Body")
    assert ok is False
    assert "authentication failed" in err.lower()
    assert events[0].closed is True

    events2, FakeSMTP2, FakeSMTP_SSL2 = _make_recorder(raise_on_send=OSError("socket reset"))
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP2)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL2)
    _patch_settings(monkeypatch, smtp_port=465)

    ok2, err2 = email_notifier.send_email("Socket Fail", "Body")
    assert ok2 is False
    assert "socket reset" in err2
    assert events2[0].closed is True


def test_disabled_or_incomplete_settings_do_not_connect(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)

    _patch_settings(monkeypatch, email_enabled=False)
    ok, err = email_notifier.send_email("Subj", "Body")
    assert ok is False
    assert "disabled" in err.lower()
    assert events == []

    _patch_settings(monkeypatch, email_enabled=True, smtp_server="")
    ok2, err2 = email_notifier.send_email("Subj", "Body")
    assert ok2 is False
    assert "smtp_server" in err2
    assert events == []


def test_helper_notifications_use_send_email(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(
        monkeypatch,
        smtp_port=465,
        report_enabled=True,
        error_notifications_enabled=True,
    )

    ok_test, err_test = email_notifier.test_email_configuration()
    assert ok_test is True and err_test is None

    ok_err, err_err = email_notifier.send_error_notification("node-1", "apt failed")
    assert ok_err is True and err_err is None

    ok_rep, err_rep = email_notifier.send_update_report(
        {"node-1": True, "node-2": False},
        {"node-1": ["2026-10-17 ok"], "node-2": []},
    )
    assert ok_rep is True and err_rep is None
    assert len(events) == 3
    assert all(e.kind == "SMTP_SSL" and e.closed for e in events)


def _plain_body(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            return payload.decode() if payload is not None else ""
    raise AssertionError("no text/plain part in message")


def test_send_email_disabled_returns_exact_message(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, email_enabled=False)

    assert email_notifier.send_email("Subj", "Body") == (
        False,
        "Email notifications are disabled",
    )
    assert events == []


def test_send_email_missing_recipients_returns_incomplete_message(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, recipient_emails=[])

    assert email_notifier.send_email("Subj", "Body") == (
        False,
        "Email configuration incomplete: recipient_emails not set",
    )
    assert events == []


def test_send_email_without_credentials_skips_login(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, smtp_username="", smtp_password="")

    ok, err = email_notifier.send_email("Subj", "Body")

    assert ok is True and err is None
    assert len(events) == 1
    assert events[0].logged_in is None
    assert len(events[0].sent_messages) == 1


def test_send_email_authentication_error_returns_auth_message(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder(
        raise_on_send=smtplib.SMTPAuthenticationError(535, b"authentication failed")
    )
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch)

    assert email_notifier.send_email("Subj", "Body") == (
        False,
        "SMTP authentication failed. Check username and password.",
    )
    assert events[0].closed is True


def test_update_report_disabled_returns_exact_message(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, report_enabled=False)

    assert email_notifier.send_update_report({"node-1": True}, {}) == (
        False,
        "Scheduled reports are disabled",
    )
    assert events == []


def test_update_report_email_mentions_the_hosts(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, report_enabled=True)

    ok, err = email_notifier.send_update_report(
        {"node-1": True, "node-2": False},
        {"node-1": ["2026-10-17 ok"], "node-2": []},
    )

    assert ok is True and err is None
    assert len(events) == 1
    msg = events[0].sent_messages[0]
    assert "System Report" in msg["Subject"]
    body = _plain_body(msg)
    assert "node-1: ONLINE" in body
    assert "node-2: OFFLINE" in body
    assert "2026-10-17 ok" in body


def test_error_notification_disabled_returns_exact_message(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, error_notifications_enabled=False)

    assert email_notifier.send_error_notification("node-1", "apt failed") == (
        False,
        "Error notifications are disabled",
    )
    assert events == []


def test_error_notification_email_mentions_host_and_error(monkeypatch):
    events, FakeSMTP, FakeSMTP_SSL = _make_recorder()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    _patch_settings(monkeypatch, error_notifications_enabled=True)

    ok, err = email_notifier.send_error_notification("node-9", "disk full")

    assert ok is True and err is None
    assert len(events) == 1
    msg = events[0].sent_messages[0]
    assert "node-9" in msg["Subject"]
    body = _plain_body(msg)
    assert "Host: node-9" in body
    assert "disk full" in body

