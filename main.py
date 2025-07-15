# updated_notice_bot.py
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

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Files and Constants
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
    "2nd sem", "2 nd semester", "second sem", "sem ii", "sem-2",
    "sem2", "2ndsem", "2ndsem result", "result of 2nd semester",
    "wbsu 2nd semester", "2nd sem result", "2nd sem notice",
    "routine for 2nd sem", "2nd semester exam date", "ii sem practical"
]

# Logging Setup
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

    def load_data(self, file, default):
        try:
            if os.path.exists(file):
                with open(file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Load error {file}: {e}")
        return default

    def save_data(self, file, data):
        try:
            with open(file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Save error {file}: {e}")

    def get_time(self):
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
            r = requests.post(url, json=payload, timeout=10)
            return r.json()
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
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
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=data, headers=headers)
            return r.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"GROQ error: {e}")
            return "GROQ unavailable. Try again later."

    def scrape_site(self, site):
        try:
            res = requests.get(site['url'], verify=False, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            notices = []
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '')
                if any(k in text for k in KEYWORDS):
                    full_link = href if href.startswith('http') else f"{site['url'].rstrip('/')}/{href.lstrip('/')}"
                    notice = {
                        "text": link.text.strip(),
                        "link": full_link,
                        "source": site['name'],
                        "timestamp": self.get_time()
                    }
                    if notice not in notices:
                        notices.append(notice)
            return notices
        except Exception as e:
            logger.error(f"Scraping error {site['name']}: {e}")
            return []

    def check_notices(self):
        self.last_check = self.get_time()
        new = []
        for site in URLS:
            for notice in self.scrape_site(site):
                if notice['text'] not in self.sent_notices['notices']:
                    summary = self.ask_groq(f"Summarize: {notice['text']}")
                    msg = f"*📢 {notice['source']} Notice:*
📝 {summary}
🔗 [Click Here]({notice['link']})
🕒 {notice['timestamp']}"
                    self.send_telegram(CHAT_ID, msg)
                    new.append(notice['text'])
        if new:
            self.sent_notices['notices'].extend(new)
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)
            logger.info(f"{len(new)} new notices sent.")

    def handle_command(self, chat_id, text):
        text = text.lower().strip()
        self.user_data['users'][str(chat_id)] = {
            "last_seen": self.get_time()
        }
        self.save_data(USER_DATA_FILE, self.user_data)

        if text in ["/start", "start"]:
            self.send_telegram(chat_id, "👋 Welcome to *WBSU Notice Bot*!\n\nUse /notice to get the latest semester updates.\nBot auto-checks every 5 minutes ⏱️")

        elif "/notice" in text:
            msg = "🔍 Checking latest notices..."
            self.send_telegram(chat_id, msg)
            all = []
            for site in URLS:
                all += self.scrape_site(site)
            if all:
                for n in all[:MAX_NOTICES]:
                    self.send_telegram(chat_id, f"*{n['source']}*\n{n['text']}\n🔗 [View]({n['link']})")
            else:
                self.send_telegram(chat_id, "📭 No new notices found right now.")

        else:
            reply = self.ask_groq(text)
            self.send_telegram(chat_id, reply)

    def polling(self):
        offset = None
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"offset": offset, "timeout": 30}
                r = requests.get(url, params=params).json()
                if not r.get("ok"): continue
                for update in r.get("result", []):
                    offset = update['update_id'] + 1
                    msg = update.get('message', {})
                    chat_id = msg.get('chat', {}).get('id')
                    text = msg.get('text', '')
                    if text:
                        self.handle_command(chat_id, text)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(10)

    def notice_loop(self):
        logger.info("Notice loop started")
        self.send_telegram(CHAT_ID, f"🤖 Bot Activated\nLast Checked: {self.get_time()}")
        while True:
            try:
                self.check_notices()
            except Exception as e:
                logger.error(f"Loop error: {e}")
            time.sleep(CHECK_INTERVAL)

bot = NoticeBot()

@app.route('/')
def home():
    return "🤖 WBSU Notice Bot Running"

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    msg = update.get('message', {})
    chat_id = msg.get('chat', {}).get('id')
    text = msg.get('text', '')
    if text:
        bot.handle_command(chat_id, text)
    return 'OK', 200

def run():
    threading.Thread(target=bot.notice_loop, daemon=True).start()
    threading.Thread(target=bot.polling, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == '__main__':
    run()