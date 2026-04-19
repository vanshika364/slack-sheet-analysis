import os
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ---------------- ENV ----------------
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# ---------------- SLACK ----------------
slack_app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET
)

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
SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

sheet_service = build("sheets", "v4", credentials=credentials)

def append_to_sheet(row):
    sheet_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A:C",
        valueInputOption="RAW",
        body={"values": [row]}
    ).execute()

# ---------------- SLACK HANDLER ----------------
@slack_app.message("")
def handle_mention(event, say, logger):
    logger.info("🔥 APP MENTION TRIGGERED")

    text = event.get("text")
    logger.info(f"TEXT: {text}")

    try:
        ai_reply = ask_openai(text)
        logger.info("OPENAI SUCCESS")

        say(ai_reply)

    except Exception as e:
        logger.error(f"ERROR: {e}")
        say("⚠️ Bot error occurred")

# ---------------- ROUTE ----------------
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# ---------------- RUN LOCAL ----------------
if __name__ == "__main__":
    flask_app.run(port=3000)