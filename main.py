import threading
import time
import requests
import urllib3
from bs4 import BeautifulSoup
import json
import os
from flask import Flask
from datetime import datetime, timedelta

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo")
CHAT_ID = os.environ.get("CHAT_ID", "6668744108")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyD8VIC30KvQ34TY34wIArmXMOH1uQa73Qo")

# Flask setup
app = Flask(__name__)

@app.route('/')
def home():
    """Return a simple status message for the Flask server."""
    return "✅ Sahil's Bot is Running"

# Telegram message sender
def send_telegram(chat_id, msg):
    """Send a message to the specified Telegram chat."""
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
    """Query the Gemini API with a given prompt."""
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
        else:
            print(f"Gemini Error Code: {response.status_code}")
            print(f"Gemini Response: {response.text}")
            return "❌ Gemini Error."
    except Exception as e:
        print(f"❌ Gemini Exception: {e}")
        return "❌ Gemini Error."

# Scrape 2nd semester updates
def get_2nd_sem_update():
    """Scrape websites for recent 2nd semester updates."""
    urls = [
        "https://www.wbsuexams.net/",
        "https://brsnc.in/",
        "https://sahilcodelab.github.io/wbsu-info/verify.html"
    ]
    keywords = [
        "2nd semester", "ii semester", "2 semester", "sem 2", "2 sem", "2sem",
        "2-nd semester", "semester 2", "semester two", "second semester",
        "2nd sem", "2 nd semester", "second sem", "sem ii", "sem-2", "sem2",
        "2ndsem", "2ndsem result", "2nd sem result", "result of 2nd semester",
        "wbsu 2nd semester"
    ]
    current_year = "2025"
    recent_days = 10

    for site in urls:
        try:
            response = requests.get(site, verify=False, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '').lower()
                combined = text + " " + href

                if any(keyword in text for keyword in keywords):
                    full_link = href if href.startswith("http") else site + href

                    # Check if the current year is in the link or text
                    if current_year in combined:
                        return {"text": link.text.strip(), "link": full_link, "source": site}

                    # Check for recent dates in the parent element
                    parent = link.find_parent()
                    date_text = ""
                    if parent:
                        for item in parent.find_all(string=True):
                            if any(year in item for year in ["2024", "2023"]):
                                break
                            if any(month in item.lower() for month in ["july", "aug", "sept", "2025"]):
                                date_text = item.strip()
                                break

                    # Parse date and check if it's recent
                    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
                        try:
                            parsed_date = datetime.strptime(date_text, fmt)
                            if parsed_date >= datetime.now() - timedelta(days=recent_days):
                                return {
                                    "text": link.text.strip(),
                                    "link": full_link,
                                    "source": site
                                }
                        except:
                            continue
        except Exception as e:
            print(f"❌ Error scraping {site}: {e}")
    return None

# Load and save last notice
def load_last_notice():
    """Load the last saved notice from file."""
    if os.path.exists("last_notice.json"):
        with open("last_notice.json", "r") as f:
            return json.load(f).get("notice", "")
    return ""

def save_notice(text):
    """Save the latest notice to file."""
    with open("last_notice.json", "w") as f:
        json.dump({"notice": text}, f)

# Auto notice checker
def check_notice_loop():
    """Continuously check for new 2nd semester updates."""
    send_telegram(CHAT_ID, "🤖 Bot started by Sahil.")
    while True:
        try:
            notice = get_2nd_sem_update()
            last_notice = load_last_notice()
            if notice and notice["text"] != last_notice:
                summary = ask_gemini(notice["text"])
                msg = (f"📢 New 2nd Semester Notice Found!\n\n"
                       f"📝 {summary}\n"
                       f"🔗 [{notice['text']}]({notice['link']})\n"
                       f"🌐 Source: {notice['source']}")
                send_telegram(CHAT_ID, msg)
                save_notice(notice["text"])
            else:
                print("✅ No new update.")
        except Exception as e:
            print(f"❌ Update check failed: {e}")
        time.sleep(300)

# Telegram chatbot listener
def telegram_chat_loop():
    """Listen for incoming Telegram messages and respond using Gemini."""
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"offset": offset, "timeout": 100}
            response = requests.get(url, params=params).json()
            for update in response.get("result", []):
                msg = update.get("message", {})
                user_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                if text:
                    reply = ask_gemini(text)
                    send_telegram(user_id, reply)
                offset = update["update_id"] + 1
        except Exception as e:
            print(f"❌ Telegram chat error: {e}")
        time.sleep(1)

# Run bot and server
if __name__ == "__main__":
    threading.Thread(target=check_notice_loop, daemon=True).start()
    threading.Thread(target=telegram_chat_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)