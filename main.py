# secure_notice_bot.py
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

# Environment Variables (set in Render.com dashboard)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Constants and Configuration
SENT_NOTICES_FILE = "sent_notices.json"
USER_DATA_FILE = "user_data.json"
CHECK_INTERVAL = 300  # 5 minutes
MAX_NOTICES = 5

URLS = [
    {"url": "https://www.wbsuexams.net/", "name": "WBSU Official"},
    {"url": "https://brsnc.in/", "name": "BRS Nagar College"},
    {"url": "https://sahilcodelab.github.io/wbsu-info/verify.html", "name": "Sahil's Info Hub"},
]

KEYWORDS = [
    "2nd semester", "ii semester", "2 semester", "sem 2", "2 sem", "2sem",
    "2-nd semester", "semester 2", "semester two", "second semester",
    "2nd sem", "2 nd semester", "second sem", "sem ii", "sem-2",
    "sem2", "2ndsem", "2ndsem result", "result of 2nd semester",
    "wbsu 2nd semester", "2nd sem result", "2nd sem notice",
    "routine for 2nd sem", "2nd semester exam date", "ii sem practical"
]

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
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
            response = requests.post(url, json=payload, timeout=10)
            if not response.json().get('ok'):
                logger.error(f"Telegram API error: {response.text}")
            return response.json()
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return None

    def ask_groq(self, prompt):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        data = {
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "model": "llama3-8b-8192"
        }
        try:
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=data, headers=headers)
            return res.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"GROQ API error: {e}")
            return "❌ GROQ service unavailable"

    def scrape_site(self, site_info):
        try:
            response = requests.get(site_info["url"], verify=False, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            notices = []
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '')
                if any(keyword in text for keyword in KEYWORDS):
                    full_link = href if href.startswith('http') else f"{site_info['url'].rstrip('/')}/{href.lstrip('/')}"
                    notice = {
                        "text": link.text.strip(),
                        "link": full_link,
                        "source": site_info["name"],
                        "timestamp": self.get_ist_time()
                    }
                    if notice not in notices:
                        notices.append(notice)
            return notices
        except Exception as e:
            logger.error(f"Error scraping {site_info['name']}: {e}")
            return []

    def check_notices(self):
        self.last_check = self.get_ist_time()
        new_notices = []
        for site in URLS:
            for notice in self.scrape_site(site):
                if notice['text'] not in self.sent_notices['notices']:
                    summary = self.ask_groq(f"Summarize in one line: {notice['text']}")
                    msg = f"\ud83d\udce2 *{notice['source']} Notice:*
\n\ud83d\udcdd {summary}
\n\ud83d\udd17 [View Notice]({notice['link']})
\n\u23f0 {notice['timestamp']}"
                    self.send_telegram(CHAT_ID, msg)
                    new_notices.append(notice['text'])
        if new_notices:
            self.sent_notices['notices'].extend(new_notices)
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)
            logger.info(f"Sent {len(new_notices)} new notices")

    def notice_loop(self):
        logger.info("\u23f3 Starting notice checker loop...")
        self.send_telegram(CHAT_ID, f"\ud83e\udd16 WBSU Notice Bot Activated!\nLast Check: {self.get_ist_time()}")
        while True:
            try:
                self.check_notices()
            except Exception as e:
                logger.error(f"Error in notice loop: {e}")
            time.sleep(CHECK_INTERVAL)

    def telegram_polling(self):
        offset = None
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"offset": offset, "timeout": 30}
                res = requests.get(url, params=params).json()
                if not res.get("ok"):
                    continue
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")
                    if text:
                        self.send_telegram(chat_id, f"You said: `{text}`")
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(10)

bot = NoticeBot()

@app.route('/')
def home():
    return "\ud83e\udd16 WBSU Notice Bot Running Securely"

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if 'message' in update:
        message = update['message']
        chat_id = message['chat']['id']
        text = message.get('text', '').strip()
        if text:
            bot.send_telegram(chat_id, f"Received: `{text}`")
    return 'OK', 200

def run_bot():
    threading.Thread(target=bot.notice_loop, daemon=True).start()
    threading.Thread(target=bot.telegram_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    run_bot()

