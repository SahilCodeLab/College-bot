import threading
import time
import requests
import json
import os
import urllib3
from bs4 import BeautifulSoup
from flask import Flask

# 🔕 Disable SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ✅ Configuration
BOT_TOKEN = '8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo'
CHAT_ID = '6668744108'
GEMINI_API_KEY = 'YOUR_GEMINI_API_KEY_HERE'
URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ✅ Flask App (for Render)
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Sahil's Smart Bot is Running!"

# ✅ Get 2nd Semester Update
def get_2nd_sem_update():
    websites = [
        "https://www.wbsuexams.net/",
        "https://brsnc.in/"
        "https://sahilcodelab.github.io/wbsu-info/verify.html"
    ]
    sem_keywords = [
        "2nd semester", "ii semester", "sem 2", "2 sem",
        "semester two", "2sem", "2 nd sem"
    ]

    for url in websites:
        try:
            r = requests.get(url, verify=False, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')

            for link in soup.find_all('a'):
                text = link.text.strip()
                href = link.get('href')
                text_lower = text.lower()

                if any(key in text_lower for key in sem_keywords):
                    full_link = href if href.startswith("http") else url + href
                    return {
                        "text": text,
                        "link": full_link,
                        "source": url
                    }

        except Exception as e:
            print(f"❌ Error scraping {url}: {e}")
    return None

# ✅ Load/Save last notice
def load_last():
    if os.path.exists("last_notice.json"):
        with open("last_notice.json", "r") as f:
            return json.load(f).get("notice")
    return ""

def save_notice(notice_text):
    with open("last_notice.json", "w") as f:
        json.dump({"notice": notice_text}, f)

# ✅ Telegram Send
def send_telegram(chat_id, msg):
    data = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "Markdown"
    }
    requests.post(f"{URL}/sendMessage", data=data)

# ✅ Gemini API
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
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        headers=headers,
        data=json.dumps(data)
    )
    if r.status_code == 200:
        return r.json()['candidates'][0]['content']['parts'][0]['text']
    else:
        return "❌ Gemini Error."

# ✅ Auto-notice Thread
def update_checker():
    send_telegram(CHAT_ID, "🤖 Auto-notice bot started.")
    while True:
        try:
            notice = get_2nd_sem_update()
            old = load_last()
            if notice and notice["text"] != old:
                summary = ask_gemini(notice["text"]) or notice["text"]
                msg = f"📢 *New 2nd Semester Update!*\n\n📝 {summary}\n\n🔗 [Open Notice]({notice['link']})\n🌐 Source: {notice['source']}"
                send_telegram(CHAT_ID, msg)
                save_notice(notice["text"])
            else:
                print("✅ No new update.")
        except Exception as e:
            print("❌ Update checker error:", e)
        time.sleep(600)  # 10 min

# ✅ Gemini Chat Thread
def gemini_chatbot():
    offset = None
    while True:
        try:
            updates = requests.get(f"{URL}/getUpdates", params={"offset": offset, "timeout": 100}).json()
            for update in updates.get("result", []):
                message = update.get("message", {})
                chat_id = message["chat"]["id"]
                user_msg = message.get("text", "")

                if user_msg:
                    print(f"👤 {chat_id}: {user_msg}")
                    reply = ask_gemini(user_msg)
                    send_telegram(chat_id, reply)
                offset = update["update_id"] + 1
        except Exception as e:
            print("❌ Gemini chat error:", e)
        time.sleep(1)

# ✅ Start All Threads
if __name__ == '__main__':
    threading.Thread(target=update_checker).start()
    threading.Thread(target=gemini_chatbot).start()
    app.run(host='0.0.0.0', port=10000)