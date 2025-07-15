# main.py
import threading
import time
import requests
import urllib3
from bs4 import BeautifulSoup
import json
import os
from flask import Flask, request
import logging
from datetime import datetime
import pytz

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment Variables (Set these in Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Configuration
SENT_NOTICES_FILE = "sent_notices.json"
USER_DATA_FILE = "user_data.json"
CHECK_INTERVAL = 300  # 5 minutes
MAX_NOTICES = 5

URLS = [
    {"url": "https://www.wbsuexams.net/", "name": "WBSU Official"},
    {"url": "https://brsnc.in/", "name": "BRS Nagar College"},
    {"url": "https://sahilcodelab.github.io/wbsu-info/verify.html", "name": "Sahil's Info Hub"}
]

KEYWORDS = [
    "2nd semester", "ii semester", "2 semester", "sem 2", "2 sem", "2sem",
    "2-nd semester", "semester 2", "semester two", "second semester",
    "2nd sem", "2 nd semester", "second sem", "sem ii", "sem-2",
    "sem2", "2ndsem", "2ndsem result", "result of 2nd semester",
    "wbsu 2nd semester", "2nd sem result", "2nd sem notice",
    "routine for 2nd sem", "2nd semester exam date", "ii sem practical"
]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
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
            logger.error(f"Error loading {filename}: {e}")
        return default

    def save_data(self, filename, data):
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")

    def get_ist_time(self):
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')

    def send_telegram(self, chat_id, message):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            if not res.json().get('ok'):
                logger.error(f"Telegram error: {res.text}")
            return res.json()
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return None

    def ask_groq(self, prompt):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "model": "llama3-8b-8192"
        }
        try:
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=data, headers=headers)
            return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.error(f"GROQ error: {e}")
            return "New notice released."

    def scrape_site(self, site_info):
        try:
            res = requests.get(site_info["url"], verify=False, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            notices = []
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '')
                if any(keyword in text for keyword in KEYWORDS):
                    full_link = href if href.startswith('http') else f"{site_info['url'].rstrip('/')}/{href.lstrip('/')}"
                    notices.append({
                        "text": link.text.strip(),
                        "link": full_link,
                        "source": site_info["name"],
                        "timestamp": self.get_ist_time()
                    })
            return notices
        except Exception as e:
            logger.error(f"Scrape error: {e}")
            return []

    def check_notices(self):
        self.last_check = self.get_ist_time()
        new_notices = []
        for site in URLS:
            for notice in self.scrape_site(site):
                if "2024" in notice["text"].lower() or "2023" in notice["text"].lower():
                    continue  # 🛑 Skip old year
                if notice["text"] not in self.sent_notices["notices"]:
                    summary = self.ask_groq(f"Summarize this in 1 short line: {notice['text']}")
                    msg = (
                        f"🔔 *{notice['source']} Notice:*\n\n"
                        f"📝 {summary}\n\n"
                        f"🔗 [Open Notice]({notice['link']})\n"
                        f"🕒 {notice['timestamp']}"
                    )
                    self.send_telegram(CHAT_ID, msg)
                    new_notices.append(notice["text"])
        if new_notices:
            self.sent_notices["notices"].extend(new_notices)
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)
            logger.info(f"📬 Sent {len(new_notices)} new notices.")

    def telegram_polling(self):
        offset = None
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                res = requests.get(url, params={"offset": offset, "timeout": 30}).json()
                if res.get("ok"):
                    for update in res["result"]:
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "")
                        if text.startswith("/"):
                            self.handle_command(chat_id, text)
                        else:
                            self.send_telegram(chat_id, "👋 Hello! I'm your friendly WBSU Notice Bot.\nType /notice to check latest updates.")
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(5)

    def handle_command(self, chat_id, command):
        command = command.strip().lower()
        if chat_id not in self.user_data["users"]:
            self.user_data["users"][str(chat_id)] = {
                "first_seen": self.get_ist_time(),
                "last_active": self.get_ist_time()
            }
        else:
            self.user_data["users"][str(chat_id)]["last_active"] = self.get_ist_time()
        self.save_data(USER_DATA_FILE, self.user_data)

        if command == "/start":
            msg = (
                "🎓 *Welcome to WBSU Notice Bot!*\n\n"
                "I auto-check for 2nd sem notices every 5 mins.\n\n"
                "📌 *Available Commands:*\n"
                "`/notice` - Get latest notices\n"
                "`/status` - Bot health\n"
                "`/help` - Show commands again"
            )
            self.send_telegram(chat_id, msg)
        elif command == "/notice":
            notices = []
            for site in URLS:
                notices.extend(self.scrape_site(site))
            filtered = [n for n in notices if "2024" not in n["text"].lower() and "2023" not in n["text"].lower()]
            if filtered:
                for notice in filtered[:MAX_NOTICES]:
                    summary = self.ask_groq(f"Short summary: {notice['text']}")
                    self.send_telegram(chat_id, f"🔔 *{notice['source']}*\n📝 {summary}\n🔗 [View]({notice['link']})")
            else:
                self.send_telegram(chat_id, "📭 No recent 2nd semester notices found.")
        elif command == "/status":
            msg = (
                f"🤖 *Bot Status*\n\n"
                f"⏰ Last Checked: {self.last_check or 'Not checked yet'}\n"
                f"📌 Notices Tracked: {len(self.sent_notices['notices'])}\n"
                f"👤 Users: {len(self.user_data['users'])}\n"
                f"⏱️ Checking every {CHECK_INTERVAL//60} min"
            )
            self.send_telegram(chat_id, msg)
        elif command == "/help":
            self.handle_command(chat_id, "/start")
        else:
            self.send_telegram(chat_id, "❓ I didn't understand. Type /help for options.")

bot = NoticeBot()

@app.route("/")
def home():
    return "🤖 WBSU Notice Bot is Running"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.json
    if 'message' in update:
        message = update['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')
        if text:
            bot.handle_command(chat_id, text)
    return 'OK', 200

def run_bot():
    threading.Thread(target=bot.check_notices, daemon=True).start()
    threading.Thread(target=bot.telegram_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    run_bot()