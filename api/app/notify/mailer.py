"""Send email through one small interface: console (dev), SMTP, or Amazon SES."""

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from app.settings import get_settings

log = logging.getLogger("app.notify")


@dataclass
class Attachment:
    filename: str
    data: bytes
    mime_type: str = "application/pdf"


@dataclass
class Email:
    to: str
    subject: str
    text: str
    attachments: list[Attachment] = field(default_factory=list)

    def build(self, sender: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, self.to, self.subject
        msg.set_content(self.text)
        for a in self.attachments:
            maintype, _, subtype = a.mime_type.partition("/")
            msg.add_attachment(
                a.data, maintype=maintype, subtype=subtype or "octet-stream", filename=a.filename
            )
        return msg


class Mailer(Protocol):
    def send(self, email: Email) -> None: ...


class ConsoleMailer:
    """Logs instead of sending; keeps the last messages for tests and local dev."""

    def __init__(self) -> None:
        self.outbox: list[Email] = []

    def send(self, email: Email) -> None:
        self.outbox.append(email)
        names = ", ".join(a.filename for a in email.attachments) or "none"
        log.info("email (console) to=%s subject=%r attachments=%s", email.to, email.subject, names)


class SMTPMailer:
    def send(self, email: Email) -> None:
        s = get_settings()
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(email.build(s.mail_from))


class SESMailer:
    def __init__(self) -> None:
        import boto3

        self.client = boto3.client("ses", region_name=get_settings().aws_region)

    def send(self, email: Email) -> None:
        raw = email.build(get_settings().mail_from).as_bytes()
        self.client.send_raw_email(RawMessage={"Data": raw})


@lru_cache
def get_mailer() -> Mailer:
    backend = get_settings().mail_backend
    if backend == "smtp":
        return SMTPMailer()
    if backend == "ses":
        return SESMailer()
    return ConsoleMailer()
