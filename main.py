import threading
import time
import requests
import urllib3
from bs4 import BeautifulSoup
import json
import os
from flask import Flask

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "YOUR_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

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

app = Flask(__name__)
@app.route('/')
def home():
    return "✅ Sahil's Smart Bot is Running"

# ✅ Send Telegram Message
def send_telegram(chat_id, msg):
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

# ✅ Gemini Summary
def ask_gemini(prompt):
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
        return "❌ Gemini summary error."
    except Exception as e:
        print(f"❌ Gemini Exception: {e}")
        return "❌ Gemini error."

# ✅ Scraper
def get_all_2nd_sem_updates():
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

# ✅ Load/Save Notices
def load_sent_notices():
    if os.path.exists(SENT_NOTICES_FILE):
        with open(SENT_NOTICES_FILE, "r") as f:
            return json.load(f).get("notices", [])
    return []

def save_sent_notices(notices):
    with open(SENT_NOTICES_FILE, "w") as f:
        json.dump({"notices": notices}, f)

# ✅ Notice Checker Loop
def check_notice_loop():
    send_telegram(CHAT_ID, "🤖 Bot started by Sahil!")
    sent_notices = load_sent_notices()
    while True:
        try:
            found_notices = get_all_2nd_sem_updates()
            for notice in found_notices:
                if notice['text'] not in sent_notices:
                    prompt = f"Summarize this: '{notice['text']}' in 1 line"
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
        except Exception as e:
            print(f"❌ Update check failed: {e}")
        time.sleep(300)

# ✅ Telegram Chat Commands
def telegram_chat_loop():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"offset": offset, "timeout": 100}
            res = requests.get(url, params=params).json()
            for update in res.get("result", []):
                msg = update.get("message", {})
                user_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                if not text: continue
                print("📩 Received:", text)
                if text == "/start":
                    send_telegram(user_id, "👋 Welcome to WBSU Notifier Bot! Use /notice to get latest update.")
                elif text == "/notice":
                    updates = get_all_2nd_sem_updates()
                    if updates:
                        for notice in updates:
                            send_telegram(user_id, f"🔔 {notice['text']}\n🔗 {notice['link']}")
                    else:
                        send_telegram(user_id, "📭 No new notices found.")
                else:
                    reply = ask_gemini(text)
                    send_telegram(user_id, reply)
                offset = update["update_id"] + 1
        except Exception as e:
            print("❌ Chat Error:", e)
        time.sleep(2)

# ✅ Start Flask + Threads
if __name__ == "__main__":
    threading.Thread(target=check_notice_loop, daemon=True).start()
    threading.Thread(target=telegram_chat_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)