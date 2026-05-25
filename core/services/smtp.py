import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from core.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS


def send_html_email(
    to: list[str],
    cc: list[str],
    subject: str,
    html_body: str,
    attachment_eml: bytes = None,
    attachment_name: str = "original.eml",
):
    msg = MIMEMultipart("mixed")
    msg["From"] = SMTP_USER
    msg["To"] = "; ".join(to)
    msg["Cc"] = "; ".join(cc)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if attachment_eml:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_eml)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=attachment_name)
        msg.attach(part)

    all_recipients = to + cc
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, all_recipients, msg.as_bytes())

    return {"success": True, "recipients": all_recipients}
