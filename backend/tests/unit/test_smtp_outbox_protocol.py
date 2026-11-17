from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from email.message import EmailMessage
import errno
import smtplib
import socket
import socketserver
from threading import Lock, Thread
from typing import Any, Literal

import pytest

from core.mail_budget import MailReservation, mail_delivery_context
from modules.notifications import tasks


class _ScriptedSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.messages: list[bytes] = []
        self.commands: list[str] = []
        self._state_lock = Lock()
        super().__init__(("127.0.0.1", 0), _SMTPHandler)

    def record_command(self, command: str) -> None:
        with self._state_lock:
            self.commands.append(command)

    def record_message(self, message: bytes) -> None:
        with self._state_lock:
            self.messages.append(message)


class _SMTPHandler(socketserver.StreamRequestHandler):
    server: _ScriptedSMTPServer

    def _reply(self, line: bytes) -> None:
        self.wfile.write(line + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        if self.server.scenario == "greeting-421":
            self._reply(b"421 service temporarily unavailable")
            return

        self._reply(b"220 local test SMTP")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            command = raw.decode("ascii", errors="replace").rstrip("\r\n")
            verb = command.partition(" ")[0].upper()
            self.server.record_command(command)

            if verb == "EHLO":
                self.wfile.write(b"250-local.test\r\n250 SIZE 1048576\r\n")
                self.wfile.flush()
            elif verb == "HELO":
                self._reply(b"250 local.test")
            elif verb == "MAIL":
                if self.server.scenario == "mail-451":
                    self._reply(b"451 retry MAIL later")
                else:
                    self._reply(b"250 sender accepted")
            elif verb == "RCPT":
                if self.server.scenario == "rcpt-450":
                    self._reply(b"450 recipient temporarily unavailable")
                else:
                    self._reply(b"250 recipient accepted")
            elif verb == "DATA":
                if self.server.scenario == "data-451":
                    self._reply(b"451 DATA temporarily unavailable")
                    continue

                self._reply(b"354 send message")
                lines: list[bytes] = []
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    if line == b".\r\n":
                        break
                    lines.append(line)
                self.server.record_message(b"".join(lines))

                if self.server.scenario == "disconnect-after-body":
                    try:
                        self.request.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.request.close()
                    return

                self._reply(b"250 message accepted")
            elif verb in {"RSET", "NOOP"}:
                self._reply(b"250 ok")
            elif verb == "QUIT":
                self._reply(b"221 bye")
                return
            else:
                self._reply(b"500 unsupported command")


@contextmanager
def _smtp_server(scenario: str) -> Iterator[_ScriptedSMTPServer]:
    server = _ScriptedSMTPServer(scenario)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["To"] = "recipient@example.test"
    message["Subject"] = "SMTP protocol regression"
    message.set_content("Reminder body")
    return message


def _connect_without_tls(
    session: tasks.SmtpSession,
    server: _ScriptedSMTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, port = server.server_address[0], server.server_address[1]
    monkeypatch.setattr(
        session,
        "_connect",
        lambda: smtplib.SMTP(str(host), int(port), timeout=2),
    )


@pytest.mark.parametrize(
    ("scenario", "expected_exception"),
    [
        pytest.param("greeting-421", smtplib.SMTPConnectError, id="421-greeting"),
        pytest.param("mail-451", smtplib.SMTPResponseException, id="451-mail"),
        pytest.param("rcpt-450", smtplib.SMTPRecipientsRefused, id="450-recipient"),
        pytest.param("data-451", smtplib.SMTPDataError, id="451-before-body"),
    ],
)
def test_real_smtplib_marks_rejection_before_body_retryable(
    scenario: str,
    expected_exception: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _smtp_server(scenario) as server:
        session = tasks.SmtpSession()
        _connect_without_tls(session, server, monkeypatch)
        try:
            with pytest.raises(expected_exception):
                session._send_sync(_message())
            assert session._last_pre_data_failure is True
            assert server.messages == []
        finally:
            session.close()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            OSError(errno.ENETUNREACH, "network unreachable"), True, id="enetunreach"
        ),
        pytest.param(
            OSError(errno.EHOSTUNREACH, "host unreachable"), True, id="ehostunreach"
        ),
        pytest.param(
            socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure"),
            True,
            id="dns-eai-again",
        ),
        pytest.param(
            socket.gaierror(socket.EAI_NONAME, "permanent DNS failure"),
            False,
            id="dns-eai-noname",
        ),
        pytest.param(OSError(errno.EIO, "unclassified I/O error"), False, id="eio"),
    ],
)
def test_pre_data_network_error_classification(error: OSError, expected: bool) -> None:
    assert tasks._is_retryable_pre_data_error(error) is expected


@pytest.mark.asyncio
async def test_mail_wrapper_does_not_report_retryable_pre_data_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = tasks.SmtpSession()
    reports: list[dict[str, Any]] = []

    async def fail_before_data(*_args: Any, **_kwargs: Any) -> bool:
        session.last_delivery_attempted = True
        session.last_delivery_retryable = True
        raise ConnectionError("temporary SMTP failure")

    monkeypatch.setattr(tasks, "_send_client_email", fail_before_data)
    monkeypatch.setattr(
        tasks, "report_mail_failure", lambda **kwargs: reports.append(kwargs)
    )

    result = await tasks.send_cancellation_email(
        email="client@example.com", details={}, smtp=session
    )

    assert result == {"status": "failed", "reason": "ConnectionError"}
    assert reports == []


@pytest.mark.asyncio
async def test_mail_wrapper_reports_nonretryable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = tasks.SmtpSession()
    reports: list[dict[str, Any]] = []

    async def fail(*_args: Any, **_kwargs: Any) -> bool:
        session.last_delivery_attempted = True
        raise ConnectionError("unexpected SMTP wrapper failure")

    monkeypatch.setattr(tasks, "_send_client_email", fail)
    monkeypatch.setattr(
        tasks, "report_mail_failure", lambda **kwargs: reports.append(kwargs)
    )

    result = await tasks.send_cancellation_email(
        email="client@example.com", details={}, smtp=session
    )

    assert result == {"status": "failed", "reason": "ConnectionError"}
    assert reports == [{"component": "notifications", "error_type": "ConnectionError"}]


@pytest.mark.asyncio
async def test_disconnect_after_body_is_not_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _smtp_server("disconnect-after-body") as server:
        session = tasks.SmtpSession()
        _connect_without_tls(session, server, monkeypatch)
        reservations: list[tuple[str, str]] = []
        finishes: list[dict[str, Any]] = []

        async def reserve(
            *, priority: Literal["medium"], message_id: str
        ) -> MailReservation:
            reservations.append((priority, message_id))
            return MailReservation(
                decision="admitted",
                window_id="20261116T0000+0000",
                message_key="test-key",
                attempt_token="test-token",
                priority=priority,
                tracked=False,
            )

        async def finish(_reservation: MailReservation, **result: Any) -> None:
            finishes.append(result)

        monkeypatch.setattr(tasks, "reserve_mail", reserve)
        monkeypatch.setattr(tasks, "finish_mail", finish)
        try:
            with mail_delivery_context(
                priority="medium",
                message_id="reminder:appointment-1:24h",
                retry_pre_data=True,
                reclaim_reserved=True,
            ):
                delivered = await session.send(
                    "recipient@example.test", "Reminder", "Reminder body"
                )

            assert delivered is False
            assert session.last_delivery_retryable is False
            assert reservations == [("medium", "reminder:appointment-1:24h")]
            assert finishes == [{"sent": False, "retryable": False}]
            assert len(server.messages) == 1
        finally:
            session.close()
