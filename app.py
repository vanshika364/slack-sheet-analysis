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

# ---------------- GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "/etc/secrets/service-account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ⚠️ CHANGE THESE TWO LINES TO MATCH YOUR DATA SHEET ⚠️
DATA_SHEET_TAB = "Sheet1"           # name of the tab with your data
DATA_RANGE = "Sheet1!A1:Z"          # read all columns A-Z; adjust if you have more
LOG_SHEET_TAB = "Logs"              # separate tab for conversation logs (create this tab!)

sheet_service = None
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    sheet_service = build("sheets", "v4", credentials=credentials)
    print("Google Sheets initialized successfully")
except Exception as e:
    print(f"Google Sheets init failed: {e}")


def read_sheet_data():
    """Read all data from the sheet as a list of rows."""
    if not sheet_service or not SPREADSHEET_ID:
        return None
    try:
        result = sheet_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=DATA_RANGE
        ).execute()
        values = result.get("values", [])
        print(f"Read {len(values)} rows from sheet")
        return values
    except Exception as e:
        print(f"Sheet read error: {e}")
        return None


def format_sheet_for_openai(values):
    """Convert sheet rows into a clean text table for OpenAI to analyze."""
    if not values or len(values) == 0:
        return "The sheet is empty."

    # First row = headers, rest = data
    headers = values[0]
    data_rows = values[1:]

    # Build a markdown-style table
    table_lines = ["| " + " | ".join(headers) + " |"]
    table_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in data_rows:
        # Pad short rows with empty strings
        padded = row + [""] * (len(headers) - len(row))
        table_lines.append("| " + " | ".join(str(c) for c in padded) + " |")

    return "\n".join(table_lines)


def append_to_log(user, question, answer):
    """Log conversations to a separate Logs tab (not the data tab!)."""
    if not sheet_service or not SPREADSHEET_ID:
        return
    try:
        sheet_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{LOG_SHEET_TAB}!A:D",
            valueInputOption="RAW",
            body={"values": [[datetime.utcnow().isoformat(), user, question, answer]]}
        ).execute()
        print("Logged to sheet")
    except Exception as e:
        print(f"Log append error: {e}")


def ask_openai_with_data(question, sheet_table):
    """Ask OpenAI with the sheet data as context."""
    system_prompt = f"""You are a data analyst assistant responding in Slack.
You have access to the following spreadsheet data. Analyze it accurately and answer questions with real numbers.

RULES:
- Always compute exact numbers from the data below
- Show your calculation briefly when relevant (e.g. "Total = 45+32+28 = 105")
- If the data doesn't contain what's needed, say so clearly
- Keep responses concise for Slack (use bullet points for multiple numbers)
- Format numbers cleanly (e.g. 1,234 not 1234.0)

SPREADSHEET DATA:
{sheet_table}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        temperature=0.2,  # lower temperature for accurate math
    )
    return response.choices[0].message.content


# ---------------- SLACK HANDLER ----------------
def respond_to_mention(event, say):
    try:
        text = event.get("text", "")
        user = event.get("user", "unknown")
        print(f"Processing mention from {user}: {text}")

        # Strip out the bot mention tag (e.g., "<@U0ATT8CM2P7>")
        # so we just get the user's actual question
        import re
        question = re.sub(r"<@\w+>", "", text).strip()

        if not question:
            say("Hi! Ask me a question about the data in your sheet.")
            return

        # Read current sheet data (real-time!)
        values = read_sheet_data()
        if values is None:
            say("⚠️ Couldn't read the sheet. Check permissions.")
            return

        sheet_table = format_sheet_for_openai(values)

        # Ask OpenAI with the data as context
        ai_reply = ask_openai_with_data(question, sheet_table)
        say(ai_reply)

        # Log the Q&A separately
        append_to_log(user, question, ai_reply)

    except Exception as e:
        print(f"ERROR in respond_to_mention: {e}")
        say(f"⚠️ Bot error: {e}")


@slack_app.event("app_mention")
def handle_mention(ack, event, say):
    ack()
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