"""
Gmail integration for Stormline Management Bot.
Reads tokens from stormline-ops and provides email read + send-with-approval.
"""

import base64
import json
import logging
import os
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText

import ftfy
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

TOKENS_PATH = os.path.expanduser(
    "~/.openclaw/workspace/stormline-ops/.tokens/google.json"
)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Email noise filters — skip obvious junk
NOISE_PATTERNS = [
    "unsubscribe", "newsletter", "no-reply", "noreply", "donotreply",
    "promotions", "mailer-daemon", "notifications@github", "notifications@linkedin",
    "your receipt from", "your order has", "shipping confirmation",
    "password reset", "verify your email", "security alert",
    "doordash", "uber eats", "grubhub", "spotify", "netflix",
    "out of office", "automatic reply", "auto-reply",
]

# Business-relevant classifiers
CLASSIFIERS = {
    "BID_INVITE": ["invitation to bid", "itb", "request for proposal", "rfp",
                   "bid request", "rfq", "bid due", "bid invitation",
                   "looking for pricing", "please provide pricing", "bid opportunity"],
    "SUPPLIER_QUOTE": ["quote", "quotation", "pricing", "material quote",
                       "winwater", "national meter", "gerardo", "hd supply",
                       "ferguson", "fortiline"],
    "PLAN_DELIVERY": ["plans attached", "drawing", "civil plans", "plan set",
                      "construction documents", "bid set"],
    "CHANGE_ORDER": ["change order", "co #", "co#", "revised scope", "extra work"],
    "INVOICE": ["invoice", "payment", "remittance", "past due", "pay application"],
    "GC_COMMUNICATION": ["schedule update", "pre-con", "preconstruction",
                         "progress", "weekly report", "site meeting"],
}


def _load_creds() -> Credentials:
    if not os.path.exists(TOKENS_PATH):
        raise RuntimeError(f"Google tokens not found at {TOKENS_PATH}")

    with open(TOKENS_PATH) as f:
        data = json.load(f)

    creds = Credentials(
        token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=data.get("scope", "").split(),
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token back
        data["access_token"] = creds.token
        with open(TOKENS_PATH, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Google token refreshed")

    return creds


def _classify(subject: str, body: str, from_addr: str) -> str:
    text = f"{subject} {body} {from_addr}".lower()
    for pattern in NOISE_PATTERNS:
        if pattern in text:
            return "NOISE"
    for cls, keywords in CLASSIFIERS.items():
        for kw in keywords:
            if kw in text:
                return cls
    return "GENERAL"


def _decode_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    if mime == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _decode_body(part)
        if result:
            return result
    return ""


def _decode_mime_header(value: str) -> str:
    """Decode encoded email headers, handling MIME encoding and garbled UTF-8."""
    parts = _decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    text = "".join(result)
    return ftfy.fix_text(text)

def _get_header(headers: list, name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return _decode_mime_header(h["value"])
    return ""


def list_emails(max_results: int = 20, query: str = "") -> list[dict]:
    """
    Fetch recent emails, classified and noise-filtered.
    query: Gmail search query, e.g. 'is:unread', 'from:tanner', etc.
    """
    creds = _load_creds()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    q = query or "newer_than:7d"
    result = service.users().messages().list(
        userId="me", maxResults=max_results, q=q
    ).execute()

    messages = result.get("messages", [])
    emails = []

    for msg in messages:
        try:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="full"
            ).execute()

            headers = detail.get("payload", {}).get("headers", [])
            subject = _get_header(headers, "Subject")
            from_addr = _get_header(headers, "From")
            date = _get_header(headers, "Date")
            body = _decode_body(detail.get("payload", {}))[:1500]

            classification = _classify(subject, body, from_addr)
            if classification == "NOISE":
                continue

            attachments = []
            for part in detail.get("payload", {}).get("parts", []):
                fname = part.get("filename", "")
                if fname:
                    attachments.append(fname)

            emails.append({
                "id": msg["id"],
                "subject": subject,
                "from": from_addr,
                "date": date,
                "snippet": detail.get("snippet", ""),
                "body": body,
                "classification": classification,
                "attachments": attachments,
                "labels": detail.get("labelIds", []),
            })
        except Exception as e:
            logger.warning(f"Failed to parse message {msg['id']}: {e}")

    return emails


def send_email(to: str, subject: str, body: str, attachment_path: str = "") -> dict:
    """Actually send an email via Gmail. Should only be called after approval."""
    import mimetypes
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders

    creds = _load_creds()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    if attachment_path and os.path.exists(attachment_path):
        msg = MIMEMultipart()
        msg.attach(MIMEText(body))
        ctype, _ = mimetypes.guess_type(attachment_path)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(attachment_path, "rb") as f:
            att = MIMEBase(maintype, subtype)
            att.set_payload(f.read())
        encoders.encode_base64(att)
        att.add_header("Content-Disposition", "attachment",
                       filename=os.path.basename(attachment_path))
        msg.attach(att)
    else:
        msg = MIMEText(body)

    msg["to"] = to
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {"sent": True, "message_id": result.get("id")}
