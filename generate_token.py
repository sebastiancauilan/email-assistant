from google_auth_oauthlib.flow import InstalledAppFlow
import json
import os

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", "480884357052-dmmhi53urq64b9hmj3pfgnd92mca22ic.apps.googleusercontent.com"),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "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"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
        }
    },
    SCOPES
)

creds = flow.run_local_server(port=0)
print(json.dumps(json.loads(creds.to_json())))