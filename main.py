import threading
import time
import requests
from bs4 import BeautifulSoup
import json
import os
import urllib3
from flask import Flask

# 🔕 SSL warnings disable
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ✅ Configs from environment or fallback default
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo"
CHAT_ID = os.environ.get("CHAT_ID") or "6668744108"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or "AIzaSyD8VIC30KvQ34TY34wIArmXMOH1uQa73Qo"

# ✅ Flask app for Render port binding
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Sahil's Bot is Running"

# ✅ Telegram message sender
def send_telegram(chat_id, msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=data)
    except:
        print("❌ Telegram send failed.")

# ✅ Gemini AI integration
def ask_gemini(prompt):
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    data = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            headers=headers,
            data=json.dumps(data)
        )
        if r.status_code == 200:
            return r.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            print("Gemini Error Code:", r.status_code)
            print("Gemini Response:", r.text)
            return "❌ Gemini Error."
    except Exception as e:
        print("❌ Gemini Exception:", e)
        return "❌ Gemini Error."

# ✅ Scrape notice for 2nd semester
def get_2nd_sem_update():
    urls = [
        "https://www.wbsuexams.net/",
        "https://brsnc.in/",
        "https://sahilcodelab.github.io/wbsu-info/verify.html"
    ]

    KEYWORDS = [
        "2nd semester",
        "ii semester",
        "2 semester",
        "sem 2",
        "2 sem",
        "2sem",
        "2-nd semester",
        "semester 2",
        "semester two",
        "second semester",
        "2nd sem",
        "2 nd semester",
        "second sem",
        "sem ii",
        "sem-2",
        "sem2",
        "2ndsem",
        "2ndsem result",
        "2nd sem result",
        "result of 2nd semester",
        "wbsu 2nd semester"
    ]

    for site in urls:
        try:
            r = requests.get(site, verify=False, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '')
                if any(k in text for k in KEYWORDS):
                    full_link = href if href.startswith("http") else site + href
                    return {
                        "text": link.text.strip(),
                        "link": full_link,
                        "source": site
                    }
        except Exception as e:
            print(f"❌ Error scraping {site}:", e)
    return None

# ✅ Load & save last notice
def load_last():
    if os.path.exists("last_notice.json"):
        with open("last_notice.json", "r") as f:
            return json.load(f).get("notice", "")
    return ""

def save_notice(text):
    with open("last_notice.json", "w") as f:
        json.dump({"notice": text}, f)

# ✅ Check notice loop (every 5 min)
def check_notice_loop():
    send_telegram(CHAT_ID, "🤖 Bot started by Sahil.")
    while True:
        try:
            notice = get_2nd_sem_update()
            old = load_last()
            if notice and notice["text"] != old:
                summary = ask_gemini(notice["text"])
                msg = f"📢 *New 2nd Semester Notice Found!*\n\n📝 {summary}\n🔗 [Open Notice]({notice['link']})\n🌐 Source: {notice['source']}"
                send_telegram(CHAT_ID, msg)
                save_notice(notice["text"])
            else:
                print("✅ No new update.")
        except Exception as e:
            print("❌ Update check failed:", e)
        time.sleep(300)  # Every 5 min

# ✅ Telegram chat listener
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
                if text:
                    reply = ask_gemini(text)
                    send_telegram(user_id, reply)
                offset = update["update_id"] + 1
        except Exception as e:
            print("❌ Telegram chat error:", e)
        time.sleep(1)

# ✅ Start Flask + threads
if __name__ == "__main__":
    threading.Thread(target=check_notice_loop).start()
    threading.Thread(target=telegram_chat_loop).start()
    app.run(host='0.0.0.0', port=10000)