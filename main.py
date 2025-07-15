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

# Configuration
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PORT = int(os.environ.get("PORT", 10000))

# Constants
SENT_NOTICES_FILE = "sent_notices.json"
USER_DATA_FILE = "user_data.json"
LOG_FILE = "bot.log"
CHECK_INTERVAL = 300  # 5 minutes
MAX_NOTICES = 5  # Max notices to show in /notice command

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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class NoticeBot:
    def __init__(self):
        self.last_check = None
        self.user_data = self.load_data(USER_DATA_FILE, {"users": {}})
        self.sent_notices = self.load_data(SENT_NOTICES_FILE, {"notices": []})

    @staticmethod
    def load_data(filename, default):
        try:
            if os.path.exists(filename):
                with open(filename, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
        return default

    def save_data(self, filename, data):
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")

    def get_ist_time(self):
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S %Z%z')

    def send_telegram(self, chat_id, msg, reply_markup=None):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        if reply_markup:
            data["reply_markup"] = reply_markup

        try:
            response = requests.post(url, json=data, timeout=10)
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.text}")
            return response.json()
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return None

    def ask_gemini(self, prompt):
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": GEMINI_API_KEY
        }
        data = {
            "contents": [{
                "parts": [{
                    "text": f"{prompt}. Keep response concise and under 200 characters."
                }]
            }]
        }

        try:
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
                headers=headers,
                json=data,
                timeout=15
            )
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            logger.error(f"Gemini API error: {response.text}")
            return "❌ Could not generate summary."
        except Exception as e:
            logger.error(f"Gemini Exception: {e}")
            return "❌ Service unavailable."

    def scrape_site(self, site_info):
        notices = []
        try:
            start_time = time.time()
            response = requests.get(site_info["url"], verify=False, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a'):
                text = link.text.strip().lower()
                href = link.get('href', '')
                
                if any(keyword in text for keyword in KEYWORDS):
                    full_link = href if href.startswith("http") else site_info["url"].rstrip('/') + '/' + href.lstrip('/')
                    
                    notice = {
                        "text": link.text.strip(),
                        "link": full_link,
                        "source": site_info["name"],
                        "timestamp": self.get_ist_time()
                    }
                    
                    if notice not in notices:  # Avoid duplicates
                        notices.append(notice)
            
            logger.info(f"Scraped {site_info['name']} in {time.time()-start_time:.2f}s")
        except Exception as e:
            logger.error(f"Error scraping {site_info['name']}: {e}")
        return notices

    def get_all_updates(self):
        all_notices = []
        with threading.ThreadPoolExecutor(max_workers=3) as executor:
            results = executor.map(self.scrape_site, URLS)
            for result in results:
                all_notices.extend(result)
        return all_notices

    def check_notices(self):
        try:
            self.last_check = self.get_ist_time()
            found_notices = self.get_all_updates()
            new_notices = []
            
            for notice in found_notices:
                if notice["text"] not in self.sent_notices["notices"]:
                    summary = self.ask_gemini(f"Summarize this notice in one line: {notice['text']}")
                    
                    msg = (
                        f"📢 *New Notice Alert!* ({notice['source']})\n\n"
                        f"📝 *{summary}*\n\n"
                        f"🔗 [View Notice]({notice['link']})\n"
                        f"⏰ {notice['timestamp']}"
                    )
                    
                    self.send_telegram(CHAT_ID, msg)
                    new_notices.append(notice["text"])
            
            if new_notices:
                self.sent_notices["notices"].extend(new_notices)
                self.save_data(SENT_NOTICES_FILE, self.sent_notices)
                logger.info(f"Sent {len(new_notices)} new notices")
            
            return new_notices
        except Exception as e:
            logger.error(f"Notice check failed: {e}")
            return []

    def check_notice_loop(self):
        logger.info("🤖 Notice checking loop started")
        self.send_telegram(CHAT_ID, f"🚀 WBSU Notice Bot Activated!\nLast check: {self.get_ist_time()}")
        
        while True:
            try:
                self.check_notices()
            except Exception as e:
                logger.error(f"Error in notice loop: {e}")
            time.sleep(CHECK_INTERVAL)

    def handle_command(self, chat_id, command):
        command = command.lower().strip()
        
        if command == "/start":
            welcome_msg = (
                "👋 *Welcome to WBSU Notice Bot!*\n\n"
                "I monitor official websites for 2nd semester updates and notify instantly.\n\n"
                "📌 *Commands:*\n"
                "/notice - Get latest notices\n"
                "/status - Check bot status\n"
                "/help - Show this message"
            )
            self.send_telegram(chat_id, welcome_msg)
            
            # Register new user
            if str(chat_id) not in self.user_data["users"]:
                self.user_data["users"][str(chat_id)] = {
                    "first_seen": self.get_ist_time(),
                    "last_active": self.get_ist_time()
                }
                self.save_data(USER_DATA_FILE, self.user_data)
        
        elif command == "/notice":
            notices = self.get_all_updates()
            if notices:
                for notice in notices[:MAX_NOTICES]:
                    self.send_telegram(
                        chat_id,
                        f"📌 *{notice['source']}*\n{notice['text']}\n🔗 [View]({notice['link']})"
                    )
            else:
                self.send_telegram(chat_id, "ℹ️ No notices found at this time.")
        
        elif command == "/status":
            status_msg = (
                f"🤖 *Bot Status*\n\n"
                f"✅ Operational\n"
                f"⏰ Last Check: {self.last_check or 'Never'}\n"
                f"👥 Users: {len(self.user_data['users'])}\n"
                f"📝 Notices Tracked: {len(self.sent_notices['notices'])}\n"
                f"🔄 Next Check in: {CHECK_INTERVAL//60} minutes"
            )
            self.send_telegram(chat_id, status_msg)
        
        elif command == "/help":
            self.handle_command(chat_id, "/start")
        
        else:
            response = self.ask_gemini(f"You are a WBSU notice bot. User asked: {command}")
            self.send_telegram(chat_id, response)

    def telegram_update_loop(self):
        logger.info("📩 Telegram update loop started")
        offset = None
        
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"offset": offset, "timeout": 25}
                
                response = requests.get(url, params=params, timeout=30)
                data = response.json()
                
                if not data.get("ok"):
                    logger.error(f"Telegram API error: {data}")
                    time.sleep(5)
                    continue
                
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    if "message" not in update:
                        continue
                    
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    text = message.get("text", "").strip()
                    
                    if not text:
                        continue
                    
                    logger.info(f"Received from {chat_id}: {text}")
                    self.handle_command(chat_id, text)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error: {e}")
                time.sleep(10)
            except Exception as e:
                logger.error(f"Update loop error: {e}")
                time.sleep(5)

# Initialize bot
bot = NoticeBot()

# Flask routes
@app.route('/')
def home():
    return "🤖 WBSU Notice Bot is Running"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        update = request.json
        if "message" in update:
            message = update["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text", "").strip()
            if text:
                bot.handle_command(chat_id, text)
        return "OK"

# Start the bot
if __name__ == "__main__":
    # Start background threads
    notice_thread = threading.Thread(target=bot.check_notice_loop, daemon=True)
    update_thread = threading.Thread(target=bot.telegram_update_loop, daemon=True)
    
    notice_thread.start()
    update_thread.start()
    
    # Run Flask app
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)