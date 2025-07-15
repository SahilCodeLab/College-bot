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
from datetime import datetime, timedelta
import pytz
import re

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Constants
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
    "sem2", "2ndsem", "result of 2nd semester", "wbsu 2nd semester",
    "2nd sem result", "2nd sem notice", "routine for 2nd sem",
    "2nd semester exam date", "ii sem practical"
]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler('bot.log')]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def is_recent_notice(text):
    patterns = [
        r"\b(\d{1,2})[/-](\d{1,2})\b",
        r"\b(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            try:
                day, month = match.groups()
                if not month.isdigit():
                    month = {
                        'jan':1, 'feb':2, 'mar':3, 'apr':4, 'may':5, 'jun':6,
                        'jul':7, 'aug':8, 'sep':9, 'oct':10, 'nov':11, 'dec':12
                    }[month[:3]]
                else:
                    month = int(month)
                day = int(day)
                notice_date = datetime(datetime.now().year, month, day)
                return datetime.now() - notice_date <= timedelta(days=7)
            except: continue
    return True  # Send if date not found

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
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M')

    def send_telegram(self, chat_id, message):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            res = requests.post(url, json=payload)
            if not res.ok:
                logger.error(f"Telegram error: {res.text}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def ask_groq(self, prompt):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama3-8b-8192",
            "messages": [{"role": "user", "content": prompt}]
        }
        try:
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=data, headers=headers)
            return res.json()['choices'][0]['message']['content'].strip()
        except:
            return "Notice found. Details inside."

    def scrape_site(self, site):
        try:
            res = requests.get(site["url"], verify=False, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            found = []
            for link in soup.find_all('a'):
                text = link.text.strip()
                href = link.get('href', '')
                if any(k in text.lower() for k in KEYWORDS) and is_recent_notice(text):
                    full = href if href.startswith('http') else site['url'].rstrip('/') + '/' + href.lstrip('/')
                    found.append({"text": text, "link": full, "source": site['name'], "timestamp": self.get_time()})
            return found
        except Exception as e:
            logger.error(f"Scrape failed {site['name']}: {e}")
            return []

    def check_notices(self):
        self.last_check = self.get_time()
        new = []
        for site in URLS:
            for notice in self.scrape_site(site):
                if notice['text'] not in self.sent_notices['notices']:
                    summary = self.ask_groq("Summarize in 1 line: " + notice['text'])
                    msg = f"\ud83d\udd14 *{notice['source']} Notice*\n\n{summary}\n\n[Open Notice]({notice['link']})\n🕒 {notice['timestamp']}"
                    self.send_telegram(CHAT_ID, msg)
                    new.append(notice['text'])
        if new:
            self.sent_notices['notices'].extend(new)
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)

    def notice_loop(self):
        logger.info("\u23f3 Starting notice loop...")
        self.send_telegram(CHAT_ID, f"\ud83e\udd16 Bot activated! Checking every 5 mins\nLast: {self.get_time()}")
        while True:
            try:
                self.check_notices()
            except Exception as e:
                logger.error(f"Loop error: {e}")
            time.sleep(CHECK_INTERVAL)

    def telegram_polling(self):
        offset = None
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"offset": offset, "timeout": 30}
                res = requests.get(url, params=params).json()
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")
                    if not text: continue
                    if "/start" in text:
                        self.send_telegram(chat_id, "\ud83d\udce2 *Welcome! Use /notice to get updates*")
                    elif "/notice" in text:
                        self.send_telegram(chat_id, "\u23f3 Checking notices...")
                        notices = []
                        for site in URLS:
                            notices.extend(self.scrape_site(site))
                        if notices:
                            for n in notices[:MAX_NOTICES]:
                                summary = self.ask_groq("Short summary: " + n['text'])
                                self.send_telegram(chat_id, f"\ud83d\udd14 *{n['source']}*\n{summary}\n[Link]({n['link']})")
                        else:
                            self.send_telegram(chat_id, "No recent notices found.")
                    else:
                        self.send_telegram(chat_id, f"You said: `{text}`")
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(10)

bot = NoticeBot()

@app.route('/')
def home():
    return "\ud83e\udd16 Bot is live"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if 'message' in data:
        msg = data['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '')
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

