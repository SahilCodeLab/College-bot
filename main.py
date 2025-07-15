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

# Disable warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# File paths
SENT_NOTICES_FILE = "sent_notices.json"
USER_DATA_FILE = "user_data.json"

# Constants
CHECK_INTERVAL = 300  # in seconds
MAX_NOTICES = 5

# URLs to scrape
URLS = [
    {"url": "https://www.wbsuexams.net/", "name": "WBSU Official"},
    {"url": "https://brsnc.in/", "name": "BRS Nagar College"},
    {"url": "https://sahilcodelab.github.io/wbsu-info/verify.html", "name": "Sahil's Info Hub"}
]

# Keywords to match
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
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger(__name__)

# Flask app
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

    def send_telegram(self, chat_id, message, reply_markup=None):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            response = requests.post(url, json=payload, timeout=10)
            if not response.json().get('ok'):
                logger.error(f"Telegram API error: {response.text}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def ask_gemini(self, prompt):
        if not GEMINI_API_KEY:
            return "❌ Gemini API not configured"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }
        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        try:
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                headers=headers,
                json=data,
                timeout=15
            )
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            logger.error(f"Gemini API error: {response.text}")
        except Exception as e:
            logger.error(f"Gemini error: {e}")

        return "❌ AI response error"

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
        all_notices = []

        threads = []
        results = []

        def worker(site):
            results.extend(self.scrape_site(site))

        for site in URLS:
            t = threading.Thread(target=worker, args=(site,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        all_notices = results
        new_notices = []

        for notice in all_notices:
            if notice['text'] not in self.sent_notices['notices']:
                summary = self.ask_gemini(f"Summarize this notice in one line: {notice['text']}")
                msg = (
                    f"📢 *New Notice Alert!* ({notice['source']})\n\n"
                    f"📝 *{summary}*\n"
                    f"🔗 [View Notice]({notice['link']})\n"
                    f"⏰ {notice['timestamp']}"
                )
                self.send_telegram(CHAT_ID, msg)
                new_notices.append(notice['text'])

        if new_notices:
            self.sent_notices['notices'].extend(new_notices)
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)

        return new_notices

    def notice_loop(self):
        logger.info("⏳ Starting notice checker loop...")
        self.send_telegram(CHAT_ID, f"🤖 WBSU Bot is now active!\nTime: {self.get_ist_time()}")

        while True:
            try:
                self.check_notices()
            except Exception as e:
                logger.error(f"Error in notice loop: {e}")
            time.sleep(CHECK_INTERVAL)

    def handle_command(self, chat_id, command):
        command = command.lower().strip()

        # Update user activity
        self.user_data.setdefault(str(chat_id), {
            "first_seen": self.get_ist_time(),
            "last_active": self.get_ist_time()
        })
        self.user_data[str(chat_id)]["last_active"] = self.get_ist_time()
        self.save_data(USER_DATA_FILE, self.user_data)

        if command == "/start" or command == "/help":
            self.send_telegram(chat_id, (
                "👋 Welcome to *WBSU Notice Bot!*\n\n"
                "I auto-check WBSU 2nd sem notices.\n\n"
                "📌 Commands:\n"
                "/notice - Latest notices\n"
                "/status - Bot status"
            ))

        elif command == "/status":
            self.send_telegram(chat_id, (
                f"🤖 *Status*\n\n"
                f"✅ Running\n"
                f"🕒 Last Checked: {self.last_check}\n"
                f"📌 Notices Sent: {len(self.sent_notices['notices'])}"
            ))

        elif command == "/notice":
            notices = []
            for site in URLS:
                notices.extend(self.scrape_site(site))

            if not notices:
                self.send_telegram(chat_id, "📭 No new notices found.")
            else:
                for notice in notices[:MAX_NOTICES]:
                    self.send_telegram(
                        chat_id,
                        f"📌 *{notice['source']}*\n{notice['text']}\n🔗 [View]({notice['link']})"
                    )

        else:
            ai_reply = self.ask_gemini(f"User asked: {command}")
            self.send_telegram(chat_id, ai_reply)

    def telegram_polling(self):
        offset = None
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"offset": offset, "timeout": 30}
                response = requests.get(url, params=params).json()

                for update in response.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "")
                    if text:
                        self.handle_command(chat_id, text)

            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(5)


bot = NoticeBot()

@app.route('/')
def home():
    return "🤖 WBSU Notice Bot is Live"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        if text:
            bot.handle_command(chat_id, text)
    return "OK", 200


def run_bot():
    threading.Thread(target=bot.notice_loop, daemon=True).start()
    threading.Thread(target=bot.telegram_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_bot()