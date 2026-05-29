import streamlit as st
import json
import base64
import os
import pickle
from email.mime.text import MIMEText
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from streamlit_oauth import OAuth2Component

from openai import OpenAI
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

st.set_page_config(page_title="AI Email Assistant", layout="wide")
st.title("AI Email Assistant")
st.caption("Scans unread emails, drafts AI replies — approve before anything sends.")

# ── CONFIG ────────────────────────────────────────────────────────────────────
import os

OPENAI_API_KEY       = os.environ.get("OPENAI_API_KEY")
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

MAX_EMAILS     = 5
SCOPES         = ["https://www.googleapis.com/auth/gmail.modify"]
# ─────────────────────────────────────────────────────────────────────────────

client = OpenAI(api_key=OPENAI_API_KEY)

# ── SESSION STATE ─────────────────────────────────────────────────────────────
for key, default in [("emails", []), ("seen_ids", set()), ("service", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

safe_mode = st.toggle("Safe Mode (won't mark emails as read)", value=True)


# ── AUTH ──────────────────────────────────────────────────────────────────────
oauth2 = OAuth2Component(
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    "https://accounts.google.com/o/oauth2/auth",
    "https://oauth2.googleapis.com/token",
    "https://oauth2.googleapis.com/token",
    "https://oauth2.googleapis.com/revoke",
)

def get_gmail_service():
    token = st.session_state.token
    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        st.session_state.token["access_token"] = creds.token
    return build("gmail", "v1", credentials=creds)



# ── EMAIL PARSING ─────────────────────────────────────────────────────────────
def get_body(payload):
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        if part["mimeType"] == "text/plain" and part["body"].get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
    return ""


# ── AI REPLY ──────────────────────────────────────────────────────────────────
def generate_reply(sender, subject, body):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": f"""You are a professional email assistant.
Return ONLY valid JSON, no markdown, no extra text:
{{
  "category": "spam | support | inquiry | other",
  "reply": "your full reply text here"
}}

Email:
From: {sender}
Subject: {subject}
Body: {body[:2000]}
"""
        }],
        temperature=0.3
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)



# ── CREATE DRAFT ──────────────────────────────────────────────────────────────
def create_draft(service, to, subject, body):
    mime = MIMEText(body)
    mime["To"]      = to
    mime["Subject"] = f"Re: {subject}"
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()

if "token" not in st.session_state:
    result = oauth2.authorize_button(
        "Connect Gmail",
        os.environ.get("REDIRECT_URI"),
        " ".join(SCOPES),
    )
    if result and "token" in result:
        st.session_state.token = result["token"]
        st.rerun()
    else:
        st.stop()
# ── SCAN BUTTON ───────────────────────────────────────────────────────────────
if st.button("Scan Inbox"):
    st.session_state.emails = []
    with st.spinner("Connecting to Gmail..."):
        service = get_gmail_service()
        st.session_state.service = service

    results  = service.users().messages().list(userId="me", maxResults=MAX_EMAILS, q="is:unread").execute()
    messages = results.get("messages", [])

    if not messages:
        st.info("No unread emails.")
    else:
        progress = st.progress(0, text="Processing emails...")
        for i, msg in enumerate(messages):
            if msg["id"] in st.session_state.seen_ids:
                continue

            data    = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            headers = data["payload"]["headers"]
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
            sender  = next((h["value"] for h in headers if h["name"] == "From"),    "(unknown)")
            body    = get_body(data["payload"]) or data.get("snippet", "")

            progress.progress((i + 1) / len(messages), text=f"Processing: {subject[:50]}")

            try:
                result = generate_reply(sender, subject, body)
            except Exception as e:
                st.error(f"AI error: {e}")
                result = {"category": "error", "reply": "Could not generate reply."}

            st.session_state.emails.append({
                "id":       msg["id"],
                "subject":  subject,
                "sender":   sender,
                "body":     body[:500],
                "reply":    result["reply"],
                "category": result.get("category", "unknown"),
            })
            st.session_state.seen_ids.add(msg["id"])

        progress.empty()
        st.success(f"Loaded {len(st.session_state.emails)} emails")


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
st.divider()
st.metric("Emails Loaded", len(st.session_state.emails))

for email in st.session_state.emails:
    with st.container(border=True):
        st.subheader(email["subject"])
        st.text(f"From: {email['sender']}")
        st.caption(f"Category: {email['category']}")

        with st.expander("Original email"):
            st.write(email["body"] or "No body available")

        with st.expander("AI Reply"):
            reply_text = st.text_area("Edit before approving:", value=email["reply"], key=f"edit_{email['id']}", height=150)

        col1, col2 = st.columns(2)

        if col1.button("✅ Approve & Save Draft", key=f"approve_{email['id']}"):
            try:
                create_draft(st.session_state.service, email["sender"], email["subject"], reply_text)
                if not safe_mode:
                    st.session_state.service.users().messages().modify(
                        userId="me",
                        id=email["id"],
                        body={"removeLabelIds": ["UNREAD"]}
                    ).execute()
                st.success("Draft saved in Gmail!")
            except Exception as e:
                st.error(f"AI error: {e}")
                result = {"category": "error", "reply": "Could not generate reply."}

        if col2.button("❌ Skip", key=f"reject_{email['id']}"):
            st.info("Skipped.")

if not st.session_state.emails:
    st.info("Click Scan Inbox to load emails.")
