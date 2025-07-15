import threading
import time
import requests
import urllib3
from bs4 import BeautifulSoup
import json
import os
from flask import Flask

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo")
CHAT_ID = os.environ.get("CHAT_ID", "6668744108")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyD8VIC30KvQ34TY34wIArmXMOH1uQa73Qo")

# Constants
SENT_NOTICES_FILE = "sent_notices.json"
URLS = [
    "https://www.wbsuexams.net/",
    "https://brsnc.in/",
    "https://sahilcodelab.github.io/wbsu-info/verify.html"
]
KEYWORDS = [
    "2nd semester", "ii semester", "2 semester", "sem 2", "2 sem", "2sem",
    "2-nd semester", "semester 2", "semester two", "second semester",
    "2nd sem", "2 nd semester", "second sem", "sem ii", "sem-2",
    "sem2", "2ndsem", "2ndsem result", "result of 2nd semester",
    "wbsu 2nd semester", "2nd sem result", "2nd sem notice",
    "routine for 2nd sem", "2nd semester exam date", "ii sem practical"
]

# Flask setup
app = Flask(__name__)

@app.route('/')
def home():
    """Return status message for Flask server."""
    return "✅ Sahil's Multi-Match Bot is Running"

# Telegram message sender
def send_telegram(chat_id, msg):
    """Send a message to a Telegram chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")

# Gemini API interaction
def ask_gemini(prompt):
    """Query Gemini API for a one-line summary of the prompt."""
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            headers=headers,
            data=json.dumps(data)
        )
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        print(f"❌ Gemini Error Code: {response.status_code}")
        return "❌ Gemini summary error."
    except Exception as e:
        print(f"❌ Gemini Exception: {e}")
        return "❌ Gemini error."

# Scrape 2nd semester updates
def get_all_2nd_sem_updates():
    """Scrape websites for all 2nd semester notices."""
    notices = []
    for site in URLS:
        try:
            response = requests.get(site, verify=False, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '')
                if any(keyword in text for keyword in KEYWORDS):
                    full_link = href if href.startswith("http") else site + href
                    notices.append({
                        "text": link.text.strip(),
                        "link": full_link,
                        "source": site
                    })
        except Exception as e:
            print(f"❌ Error scraping {site}: {e}")
    return notices

# Load and save sent notices
def load_sent_notices():
    """Load previously sent notices from file."""
    if os.path.exists(SENT_NOTICES_FILE):
        with open(SENT_NOTICES_FILE, "r") as f:
            return json.load(f).get("notices", [])
    return []

def save_sent_notices(notices):
    """Save the list of sent notices to file."""
    with open(SENT_NOTICES_FILE, "w") as f:
        json.dump({"notices": notices}, f)

# Auto notice checker
def check_notice_loop():
    """Continuously check for new 2nd semester notices."""
    send_telegram(CHAT_ID, "🤖 Multi-match bot started by Sahil!")
    sent_notices = load_sent_notices()
    while True:
        try:
            found_notices = get_all_2nd_sem_updates()
            for notice in found_notices:
                if notice['text'] not in sent_notices:
                    prompt = f"Summarize this notice in 1 line: '{notice['text']}'"
                    summary = ask_gemini(prompt)
                    msg = (
                        f"📢 *New 2nd Semester Notice Found!*\n\n"
                        f"📝 {summary}\n\n"
                        f"🔗 [{notice['text']}]({notice['link']})\n"
                        f"🌐 Source: {notice['source']}"
                    )
                    send_telegram(CHAT_ID, msg)
                    sent_notices.append(notice['text'])
                    save_sent_notices(sent_notices)
            else:
                print("✅ No new updates.")
        except Exception as e:
            print(f"❌ Update check failed: {e}")
        time.sleep(300)  # Check every 5 minutes

# Run bot and server
if __name__ == "__main__":
    threading.Thread(target=check_notice_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)