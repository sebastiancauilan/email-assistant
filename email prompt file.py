import json
import base64
import os
import pickle
import streamlit as st

from openai import OpenAI

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

client = OpenAI(
    api_key=st.secrets["OPENAI_API_KEY"]
)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

creds = None

# load saved login if it exists
if os.path.exists("token.pickle"):
    with open("token.pickle", "rb") as token:
        creds = pickle.load(token)

# if no valid login, log in
if not creds or not creds.valid:

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    else:
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": st.secrets["GOOGLE_CLIENT_ID"],
                    "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
                }
            },
            SCOPES
        )

        auth_url, _ = flow.authorization_url(prompt="consent")

        st.link_button("Authorize Gmail", auth_url)

        code = st.text_input("Paste authorization code here")

        if not code:
            st.stop()

        flow.fetch_token(code=code)

        creds = flow.credentials

        # save login
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

# connect to Gmail
service = build("gmail", "v1", credentials=creds)

results = service.users().messages().list(
    userId="me",
    maxResults=3,
    q="is:unread"
).execute()

messages = results.get("messages", [])

for msg in messages:

    # 1. GET EMAIL
    email_data = service.users().messages().get(
        userId="me",
        id=msg["id"],
        format="full"
    ).execute()

    # 2. PARSE HEADERS
    headers = email_data["payload"]["headers"]

    subject = next(
        (h["value"] for h in headers if h["name"] == "Subject"),
        "No Subject"
    )

    sender = next(
        (h["value"] for h in headers if h["name"] == "From"),
        "Unknown Sender"
    )

    snippet = email_data.get("snippet", "")

    email_text = f"""
From: {sender}
Subject: {subject}
Body: {snippet}
"""

    # 3. AI CALL
    response = client.responses.create(
        model="gpt-5.2",
        input=f"""
Return ONLY valid JSON:

{{
  "category": "internship | sales | support | other",
  "reply": "..."
}}

Email:
{email_text}
"""
    )

    # 4. SAFE PARSE
    try:
        result = json.loads(response.output_text)

    except Exception as e:
        print("JSON parse failed:", e)
        continue

    # 5. CREATE DRAFT
    raw_email = (
        f"To: {sender}\n"
        f"Subject: Re: {subject}\n\n"
        f"{result['reply']}"
    )

    message = {
        "message": {
            "raw": base64.urlsafe_b64encode(
                raw_email.encode("utf-8")
            ).decode("utf-8")
        }
    }

    service.users().drafts().create(
        userId="me",
        body=message
    ).execute()

    # 6. OUTPUT
    print("\n--- AI RESULT ---")
    print("Category:", result["category"])
    print("Reply:", result["reply"])