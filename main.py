# dil_se_notice_bot.py
import threading
import time
import requests
import urllib3
from bs4 import BeautifulSoup
import json
import os
from flask import Flask, request
import logging
from datetime import datetime, timedelta
import pytz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

SENT_NOTICES_FILE = "sent_notices.json"
USER_DATA_FILE = "user_data.json"
CHECK_INTERVAL = 300
MAX_NOTICES = 5

URLS = [
    {"url": "https://www.wbsuexams.net/", "name": "WBSU Official"},
    {"url": "https://brsnc.in/", "name": "BRS Nagar College"},
    {"url": "https://sahilcodelab.github.io/wbsu-info/verify.html", "name": "Sahil's Info Hub"},
]

KEYWORDS = [
    "2nd semester", "ii semester", "2 semester", "sem 2", "2 sem", "2sem",
    "2-nd semester", "semester 2", "semester two", "second semester",
    "2nd sem", "second sem", "sem ii", "sem-2", "sem2", "2ndsem", "2ndsem result",
    "wbsu 2nd semester", "2nd sem result", "2nd sem notice", "routine for 2nd sem",
    "2nd semester exam date", "ii sem practical"
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler('bot.log')]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class NoticeBot:
    def __init__(self):
        self.sent_notices = self.load_data(SENT_NOTICES_FILE, {"notices": []})
        self.user_data = self.load_data(USER_DATA_FILE, {"users": {}})
        self.last_check = None

    def load_data(self, filename, default):
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Load error {filename}: {e}")
        return default

    def save_data(self, filename, data):
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Save error {filename}: {e}")

    def get_time(self):
        return datetime.now(pytz.timezone('Asia/Kolkata'))

    def send_telegram(self, chat_id, text):
        try:
            res = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }, timeout=10)
            return res.json()
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def ask_groq(self, prompt):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-8b-8192",
            "messages": [{"role": "user", "content": prompt}]
        }
        try:
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            return res.json()['choices'][0]['message']['content']
        except:
            return "\u274c Summary unavailable"

    def scrape_site(self, site):
        try:
            r = requests.get(site["url"], verify=False, timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')
            notices = []
            for a in soup.find_all("a"):
                text = a.text.strip()
                href = a.get("href", "")
                full_link = href if href.startswith("http") else site["url"].rstrip("/") + "/" + href.lstrip("/")
                if any(k in text.lower() for k in KEYWORDS):
                    if any(y in text for y in ["2023", "2022", "2021"]):
                        continue
                    notices.append({
                        "text": text,
                        "link": full_link,
                        "source": site["name"],
                        "timestamp": self.get_time().strftime("%Y-%m-%d %H:%M:%S")
                    })
            return notices
        except Exception as e:
            logger.error(f"Scrape error {site['name']}: {e}")
            return []

    def check_notices(self):
        self.last_check = self.get_time()
        new = []
        for site in URLS:
            for notice in self.scrape_site(site):
                if notice['text'] not in self.sent_notices['notices']:
                    summary = self.ask_groq(f"Summarize shortly: {notice['text']}").split(". ")[0]
                    msg = f"\ud83d\udd14 *{notice['source']} Notice*\n\n\ud83d\udcdd {summary}\n\n\ud83d\udd17 [Open Notice]({notice['link']})\n\u23f0 {notice['timestamp']}"
                    self.send_telegram(CHAT_ID, msg)
                    new.append(notice['text'])
        if new:
            self.sent_notices['notices'].extend(new)
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)

    def human_chat(self, text):
        if "/" in text:
            return None
        keywords = ["help", "udaas", "sad", "problem", "friend", "alone", "can you"]
        if any(k in text.lower() for k in keywords):
            return self.ask_groq(f"Friendly, kind and short reply to user: {text}")
        return f"👋 Hello! Type /notice to check WBSU 2nd Sem updates. I'm here if you need anything!"

    def telegram_polling(self):
        offset = None
        while True:
            try:
                res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": offset, "timeout": 30})
                for upd in res.json().get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")
                    if not text: continue
                    logger.info(f"User said: {text}")
                    if text.lower() == "/start":
                        self.send_telegram(chat_id, "\ud83d\ude0a Welcome to WBSU Notice Bot!\n\nCommands:\n/notice - Get latest\n/status - Bot status\n/help - Get help")
                    elif text.lower() == "/notice":
                        self.check_notices()
                        self.send_telegram(chat_id, "✅ Notices checked! If new found, sent above.")
                    elif text.lower() == "/status":
                        self.send_telegram(chat_id, f"\ud83d\ude80 Bot is running. Last check: {self.last_check.strftime('%H:%M %d-%m-%Y') if self.last_check else 'Not yet'}")
                    elif text.lower() == "/help":
                        self.send_telegram(chat_id, "Type /notice to see updates. Or share what's on your mind ❤\ufe0f")
                    else:
                        reply = self.human_chat(text)
                        if reply:
                            self.send_telegram(chat_id, reply)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(10)

bot = NoticeBot()

@app.route('/')
def home():
    return "\ud83e\udd16 Dil Se WBSU Notice Bot is Live."

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")
    if text:
        bot.send_telegram(chat_id, bot.human_chat(text) or "Use /notice to check updates")
    return 'OK'

def run_bot():
    threading.Thread(target=bot.check_notices, daemon=True).start()
    threading.Thread(target=bot.telegram_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == '__main__':
    run_bot()

