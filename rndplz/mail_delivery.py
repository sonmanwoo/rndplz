"""Optional outgoing mail for saved proposals over SMTP (Gmail app password).

Configured only through server environment variables; nothing is read from the
repository, the browser or the conversation. Recipient addresses live in a
JSON file outside the source tree that maps person ids to addresses, so the
public corpus never carries personal addresses. Delivery results are recorded
on the proposal with masked addresses only.
"""
import json
import os
import re
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

_ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
KIND_LABEL = {"advice": "자문 요청", "verify": "검증 요청", "member": "프로젝트 참여 요청",
              "site_request": "현장 의뢰", "resource_request": "자원 요청"}
MAX_BODY = 30000


def mask(address):
    local, _, domain = str(address).partition("@")
    return (local[:1] + "***@" + domain) if domain else "***"


def _address(value):
    value = value.strip() if isinstance(value, str) else ""
    return value if value and len(value) <= 254 and _ADDRESS.match(value) else ""


class MailDelivery:
    """SMTP delivery with a fixed sender. `transport(message)` may be injected for tests."""

    def __init__(self, env=None, transport=None, clock=None):
        env = os.environ if env is None else env
        self.host = (env.get("RNDPLZ_MAIL_SMTP_HOST") or "smtp.gmail.com").strip()
        try:
            self.port = int(env.get("RNDPLZ_MAIL_SMTP_PORT") or 587)
        except (TypeError, ValueError):
            self.port = 0
        self.username = (env.get("RNDPLZ_MAIL_USERNAME") or "").strip()
        self.password = env.get("RNDPLZ_MAIL_PASSWORD") or ""
        self.sender = _address(env.get("RNDPLZ_MAIL_FROM") or self.username)
        self.copy_to = _address(env.get("RNDPLZ_MAIL_COPY_TO") or "")
        self.recipients_path = (env.get("RNDPLZ_MAIL_RECIPIENTS_FILE") or "").strip()
        self.subject_prefix = (env.get("RNDPLZ_MAIL_SUBJECT_PREFIX") or "[수소문]").strip()
        self.service_url = (env.get("RNDPLZ_PUBLIC_ORIGIN") or "").strip()
        self._transport = transport or self._smtp_send
        self._clock = clock or time.time
        self.enabled = bool(self.username and self.password and self.sender and self.recipients_path
                            and self.host and 0 < self.port < 65536)

    def status(self):
        """Browser-safe summary: no addresses, no credentials."""
        return {"enabled": self.enabled,
                "recipients_file_present": bool(self.recipients_path and Path(self.recipients_path).is_file())}

    def address_for(self, person_id):
        if not self.recipients_path:
            return ""
        try:
            data = json.loads(Path(self.recipients_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return _address(data.get(person_id)) if isinstance(data, dict) else ""

    def send(self, proposal):
        record = {"channel": "gmail_smtp",
                  "at": datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(timespec="seconds")}
        if not self.enabled:
            return {**record, "status": "not_configured"}
        to = self.address_for(proposal.get("recipient_id", ""))
        if not to:
            return {**record, "status": "skipped_no_address"}
        body = proposal.get("body", "")
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
            return {**record, "status": "failed", "error_kind": "body_invalid"}
        message = EmailMessage()
        kind = KIND_LABEL.get(proposal.get("request_kind"), "의뢰")
        message["Subject"] = self.subject_prefix + " " + str(proposal.get("recipient_name", "")).strip() + "님께 드리는 " + kind
        message["From"] = self.sender
        message["To"] = to
        if self.copy_to and self.copy_to != to:
            message["Cc"] = self.copy_to
        footer = "\n\n--\n수소문에서 작성해 보낸 의뢰입니다. 회신은 이 메일의 보낸 사람 주소로 부탁드립니다."
        if self.service_url:
            footer += "\n서비스: " + self.service_url
        message.set_content(body + footer)
        try:
            self._transport(message)
        except Exception as exc:  # never lose the saved proposal because mail failed
            return {**record, "status": "failed", "error_kind": type(exc).__name__}
        result = {**record, "status": "sent", "to": mask(to)}
        if "Cc" in message:
            result["copy_to"] = mask(self.copy_to)
        return result

    def _smtp_send(self, message):
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(self.username, self.password)
            smtp.send_message(message)
