"""Gmail sender (same setup as the Instagram tracker): SMTP_USER, SMTP_PASS and REPORT_TO (or ALERT_TO) secrets."""
import os
import smtplib
import time
import uuid
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid


def send_email(subject, body, html=None, to=None, images=None):
    """images: {content_id: jpeg bytes}, referenced in the html as <img src="cid:content_id">."""
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    to = to or os.environ.get("REPORT_TO") or os.environ.get("ALERT_TO")
    if not (user and pw and to):
        print("Email not configured (SMTP_USER / SMTP_PASS / REPORT_TO) - skipping:", subject)
        return False
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body, "plain", "utf-8"))
    if html:
        alt.attach(MIMEText(html, "html", "utf-8"))
    if images:
        msg = MIMEMultipart("related")
        msg.attach(alt)
        for cid, data in images.items():
            img = MIMEImage(data, "jpeg")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=f"{cid}.jpg")
            msg.attach(img)
    else:
        msg = alt
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg["Message-ID"] = make_msgid(domain="ad-tracker.local")      # every email stands alone in Gmail
    msg["X-Entity-Ref-ID"] = uuid.uuid4().hex
    rcpts, host, last = [a.strip() for a in to.split(",") if a.strip()], os.environ.get("SMTP_HOST") or "smtp.gmail.com", ""
    for port in (465, 587):  # Gmail: SSL on 465; if that connection keeps dropping, STARTTLS on 587
        for attempt in range(2):
            stage = "connect"
            try:
                s = smtplib.SMTP_SSL(host, port, timeout=60) if port == 465 else smtplib.SMTP(host, port, timeout=60)
                with s:
                    if port != 465:
                        s.starttls()
                    stage = "login"
                    s.login(user.strip(), pw.strip())
                    stage = "send"
                    s.sendmail(user.strip(), rcpts, msg.as_string())
                return True
            except smtplib.SMTPAuthenticationError:
                raise  # wrong SMTP_USER / SMTP_PASS (Gmail needs an app password) - retrying won't help
            except OSError as e:  # dropped connection, timeout, refused...
                last = f"port {port}, failed at {stage}: {e}"
                print("  email:", last)
                time.sleep(5)
    raise RuntimeError("email not sent - " + last)
