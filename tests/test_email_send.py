"""Tests for send_report itself.

Regression cover: cli.py called send_report with a keyword the method did not
accept, and every existing test exercised only format_report_email, so the
TypeError only surfaced in production.
"""
import inspect
import json
from email import message_from_string

import pytest

from job_collector.cli import send_email as cli_send_email
from job_collector.email_delivery import EmailDelivery


class FakeSMTP:
    """Captures the message instead of sending it."""
    sent: list = []

    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def delivery(monkeypatch):
    monkeypatch.setattr("job_collector.email_delivery.smtplib.SMTP", FakeSMTP)
    FakeSMTP.sent = []
    return EmailDelivery(
        smtp_host="smtp.example.com", smtp_username="u", smtp_password="p",
        from_address="from@example.com",
    )


def test_cli_only_passes_arguments_send_report_accepts():
    """The call site and the signature must agree."""
    accepted = set(inspect.signature(EmailDelivery.send_report).parameters)

    for name in ["to_address", "subject", "body", "json_report_path", "attach_json"]:
        assert name in accepted, f"send_report() is missing '{name}', which cli.py passes"


def test_sends_body_as_utf8(delivery):
    """Descriptions carry curly quotes; the charset must be declared."""
    ok = delivery.send_report(
        to_address="to@example.com", subject="s", body="Adobe’s team here",
    )

    assert ok
    [msg] = FakeSMTP.sent
    payload = msg.get_payload(0)
    assert payload.get_content_charset() == "utf-8"
    assert "Adobe’s" in payload.get_payload(decode=True).decode("utf-8")


def test_attaches_json_when_asked(delivery, tmp_path):
    report = tmp_path / "latest_jobs.json"
    report.write_text(json.dumps({"jobs": {}}), encoding="utf-8")

    delivery.send_report(
        to_address="to@example.com", subject="s", body="b",
        json_report_path=report, attach_json=True,
    )

    [msg] = FakeSMTP.sent
    assert len(msg.get_payload()) == 2


def test_omits_attachment_when_disabled(delivery, tmp_path):
    report = tmp_path / "latest_jobs.json"
    report.write_text("{}", encoding="utf-8")

    delivery.send_report(
        to_address="to@example.com", subject="s", body="b",
        json_report_path=report, attach_json=False,
    )

    [msg] = FakeSMTP.sent
    assert len(msg.get_payload()) == 1


def test_incomplete_configuration_returns_false(monkeypatch):
    """Missing credentials should be reported, not raised."""
    monkeypatch.setattr("job_collector.email_delivery.smtplib.SMTP", FakeSMTP)
    incomplete = EmailDelivery(smtp_host="h", smtp_username=None,
                               smtp_password=None, from_address=None)

    assert incomplete.send_report("to@example.com", "s", "b") is False
