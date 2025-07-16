import os
import requests
import hashlib
import json
import re
import threading
import time
from datetime import datetime, timedelta
import pytz
from flask import Flask, request
from bs4 import BeautifulSoup
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
ADMIN_ID = os.environ.get('ADMIN_ID')  # 🔔 Add this in your env file
CHECK_INTERVAL = 30 if os.environ.get('TEST_MODE') else 300
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
NOTICES_FILE = os.path.join(DATA_DIR, 'notices.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# Init data

def init_data_files():
    defaults = {
        NOTICES_FILE: {"notices": {}, "last_checked": None},
        USERS_FILE: {"users": {}}
    }
    for file, default in defaults.items():
        if not os.path.exists(file):
            with open(file, 'w') as f:
                json.dump(default, f)
                logger.info(f"Initialized {file}")

init_data_files()

SEMESTERS = {
    "1": {"name": "1st Semester", "keywords": ["sem 1", "semester 1", "first sem", "1st semester", "1st sem"]},
    "2": {"name": "2nd Semester", "keywords": ["sem 2", "semester 2", "second sem", "2nd semester", "2nd sem"]},
    "3": {"name": "3rd Semester", "keywords": ["sem 3", "semester 3", "third sem", "3rd semester", "3rd sem"]},
    "4": {"name": "4th Semester", "keywords": ["sem 4", "semester 4", "fourth sem", "4th semester", "4th sem"]},
    "5": {"name": "5th Semester", "keywords": ["sem 5", "semester 5", "fifth sem", "5th semester", "5th sem"]},
    "6": {"name": "6th Semester", "keywords": ["sem 6", "semester 6", "sixth sem", "6th semester", "6th sem", "final semester"]}
}

SOURCES = [
    {
        "name": "WBSU Official",
        "url": "https://www.wbsuexams.net/",
        "selectors": {
            "container": "div.notice-board",
            "items": "a",
            "ignore": ["old-notice", "archive"]
        }
    },
    {
        "name": "Test Hub",
        "url": "https://sahilcodelab.github.io/wbsu-info/verify.html",
        "selectors": {
            "container": "body",
            "items": "a",
            "ignore": []
        }
    }
]

class NoticeBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "WBSU Notice Bot v4.4"})
        self.lock = threading.Lock()

    def _load_data(self, file):
        with self.lock:
            try:
                with open(file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {file}: {e}")
                return {"notices": {}, "last_checked": None} if file == NOTICES_FILE else {"users": {}}

    def _save_data(self, file, data):
        with self.lock:
            try:
                with open(file, 'w') as f:
                    json.dump(data, f, indent=2)
                logger.info(f"Saved data to {file}")
            except Exception as e:
                logger.error(f"Error saving {file}: {e}")

    def _get_current_time(self):
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M:%S")

    def send_telegram_message(self, chat_id, text):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
                timeout=10,
                verify=False
            )
            response.raise_for_status()
            logger.info(f"Sent message to {chat_id}: {text[:50]}...")
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return None

    def run_scheduled_checks(self):
        while True:
            try:
                logger.info("Scheduled check thread alive")
                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Scheduled check error: {e}")
                time.sleep(60)

@app.route('/')
def home():
    return "🤖 WBSU Notice Bot v4.4 Running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.json
        if 'message' in update:
            msg = update['message']
            user_id = str(msg['from']['id'])
            text = msg.get('text', '')
            bot = NoticeBot()
            bot.send_telegram_message(msg['chat']['id'], f"👋 Received your message: {text}")
        return 'OK'
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'ERROR', 500

def run_bot():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set")
        raise ValueError("Missing BOT_TOKEN")
    bot = NoticeBot()
    logger.info("Starting scheduled checks thread")
    threading.Thread(target=bot.run_scheduled_checks, daemon=True).start()
    if ADMIN_ID:
        bot.send_telegram_message(ADMIN_ID, "✅ WBSU Notice Bot is now *Active* and running!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), ssl_context=None)

if __name__ == '__main__':
    run_bot()