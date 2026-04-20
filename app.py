import os
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

# ---------------- ENV ----------------
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# ---------------- SLACK ----------------
slack_app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app = Flask(__name__)
handler = SlackRequestHandler(slack_app)

# ---------------- OPENAI ----------------
client = OpenAI(api_key=OPENAI_API_KEY)

def ask_openai(prompt):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful Slack assistant. Be concise and clear."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# ---------------- GOOGLE SHEETS ----------------
# On Render, Secret Files are mounted at /etc/secrets/<filename>
SERVICE_ACCOUNT_FILE = "/etc/secrets/service-account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

sheet_service = None
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    sheet_service = build("sheets", "v4", credentials=credentials)
    print("Google Sheets initialized successfully")
except Exception as e:
    print(f"Google Sheets init failed: {e}")

def append_to_sheet(user, question, answer):
    if not sheet_service or not SPREADSHEET_ID:
        print("Skipping sheet append — not configured")
        return
    try:
        sheet_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A:D",
            valueInputOption="RAW",
            body={"values": [[datetime.utcnow().isoformat(), user, question, answer]]}
        ).execute()
        print("Logged to sheet")
    except Exception as e:
        print(f"Sheet append error: {e}")

# ---------------- SLACK HANDLER ----------------
def respond_to_mention(event, say):
    try:
        text = event.get("text", "")
        user = event.get("user", "unknown")
        print(f"Processing mention from {user}: {text}")

        ai_reply = ask_openai(text)
        say(ai_reply)
        append_to_sheet(user, text, ai_reply)
    except Exception as e:
        print(f"ERROR in respond_to_mention: {e}")
        say("⚠️ Bot error occurred")

@slack_app.event("app_mention")
def handle_mention(ack, event, say):
    ack()  # acknowledge within 3 seconds to avoid Slack retries
    respond_to_mention(event, say)

# ---------------- ROUTES ----------------
@flask_app.route("/", methods=["GET"])
def home():
    return "BOT IS LIVE"

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

if __name__ == "__main__":
    flask_app.run(port=3000)