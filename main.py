import threading
import time
import requests
import hashlib
import difflib
from bs4 import BeautifulSoup
import json
import os
from flask import Flask, request
import logging
from datetime import datetime, timedelta
import pytz
import re

# Enhanced Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
DATA_DIR = "data"

# Constants
CHECK_INTERVAL = 300  # 5 minutes
SENT_NOTICES_FILE = f"{DATA_DIR}/sent_notices.json"
USER_DATA_FILE = f"{DATA_DIR}/user_data.json"
GROUP_IDS = json.loads(os.environ.get("GROUP_IDS", "[]"))
MAX_CONTENT_LENGTH = 1500  # For AI processing

# Enhanced Website Monitoring
URLS = [
    {
        "url": "https://www.wbsuexams.net/",
        "name": "WBSU Official",
        "selectors": {"container": "div.notice-board", "links": "a"}
    },
    {
        "url": "https://brsnc.in/",
        "name": "BRS Nagar College",
        "selectors": {"container": "div#notices", "links": "li a"}
    },
    {
        "url": "https://sahilcodelab.github.io/wbsu-info/",
        "name": "Sahil's Info Hub",
        "selectors": {"container": "div.content", "links": "a.notice"}
    }
]

# Setup advanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log'),
        logging.handlers.RotatingFileHandler('bot_debug.log', maxBytes=1e6, backupCount=3)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class AdvancedNoticeBot:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.sent_notices = self.load_data(SENT_NOTICES_FILE, {"notices": {}, "hashes": {}})
        self.user_data = self.load_data(USER_DATA_FILE, {"users": {}, "stats": {}})
        self.last_check = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "WBSU Notice Bot v2.0"})
        
    # Enhanced data handling with compression
    def load_data(self, filename, default):
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Data migration for old formats
                    if isinstance(data.get("notices"), list):
                        data["notices"] = {n: {} for n in data["notices"]}
                    return data
        except Exception as e:
            logger.error(f"Load error {filename}: {e}", exc_info=True)
        return default

    def save_data(self, filename, data):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Save error {filename}: {e}", exc_info=True)

    # Enhanced time handling with timezone awareness
    def get_time(self, fmt="%d-%m-%Y %H:%M:%S"):
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime(fmt)

    # Improved Telegram message sending with retries
    def send_telegram(self, chat_id, text, retries=3):
        for attempt in range(retries):
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "MarkdownV2",
                        "disable_web_page_preview": True,
                        "disable_notification": False
                    },
                    timeout=15
                ).json()
                
                if response.get("ok"):
                    # Update stats
                    self.user_data["stats"]["messages_sent"] = self.user_data["stats"].get("messages_sent", 0) + 1
                    return True
                
                logger.error(f"Telegram API error: {response.get('description')}")
                
            except Exception as e:
                logger.error(f"Telegram send attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        
        return False

    # Supercharged Groq AI integration
    def ask_groq(self, prompt, max_tokens=500):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        payload = {
            "model": "llama3-70b-8192",  # Using more powerful model
            "messages": [{
                "role": "user",
                "content": prompt[:MAX_CONTENT_LENGTH]  # Prevent token overflow
            }],
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "top_p": 0.9
        }
        
        try:
            start_time = time.time()
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20
            ).json()
            
            logger.info(f"Groq API response time: {time.time() - start_time:.2f}s")
            
            if "choices" in response:
                content = response['choices'][0]['message']['content']
                # Clean AI response
                content = re.sub(r"\*+", "", content).strip()
                return content if content else None
            
            logger.error(f"Groq API error: {response.get('error', {}).get('message')}")
            
        except Exception as e:
            logger.error(f"Groq API connection error: {e}")
        
        return None

    # Advanced website monitoring with diff detection
    def monitor_website(self, site):
        try:
            # Get current content
            response = self.session.get(site["url"], timeout=20, verify=False)
            response.raise_for_status()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            container = soup.select_one(site["selectors"]["container"]) or soup
            
            # Get all notice elements
            notice_elements = container.select(site["selectors"]["links"])
            
            # Generate content hash
            content_hash = hashlib.sha256(str(container).encode()).hexdigest()
            last_hash = self.sent_notices["hashes"].get(site["url"])
            
            # Check for changes
            if content_hash != last_hash:
                logger.info(f"Change detected on {site['name']}")
                
                # Get previous content for diff comparison
                previous_content = ""
                if last_hash:
                    previous_content = self.sent_notices["notices"].get(site["url"], {}).get("content", "")
                
                # Process new notices
                new_notices = []
                for element in notice_elements:
                    text = element.get_text(" ", strip=True)
                    href = element.get('href', '')
                    
                    if not text or len(text) < 10:
                        continue
                        
                    # Build full URL
                    url = href if href.startswith('http') else f"{site['url'].rstrip('/')}/{href.lstrip('/')}"
                    
                    # Check if notice is new
                    notice_id = hashlib.md5(f"{text}{url}".encode()).hexdigest()
                    if notice_id not in self.sent_notices["notices"]:
                        new_notices.append({
                            "id": notice_id,
                            "text": text,
                            "url": url,
                            "element": str(element)[:500]  # Store element HTML for debugging
                        })
                
                if new_notices:
                    # Update stored hash
                    self.sent_notices["hashes"][site["url"]] = content_hash
                    self.sent_notices["notices"][site["url"]] = {
                        "content": str(container)[:10000],  # Store partial content for diffing
                        "last_updated": self.get_time()
                    }
                    
                    return new_notices
                    
        except Exception as e:
            logger.error(f"Monitoring error for {site['name']}: {e}", exc_info=True)
        
        return []

    # Enhanced notice processing with AI
    def process_notices(self, site, notices):
        for notice in notices:
            try:
                # Generate AI summary in Hinglish
                summary_prompt = (
                    f"WBSU notice in 1 line Romazid Hindi (Hinglish):\n"
                    f"Original: {notice['text']}\n\n"
                    f"Context: This is a university notice for 2nd semester students. "
                    f"Make it friendly and concise (max 15 words). "
                    f"Highlight if urgent or important."
                )
                
                summary = self.ask_groq(summary_prompt) or notice['text']
                
                # Create message
                message = (
                    f"📢 **{site['name']} Update**\n\n"
                    f"{summary}\n\n"
                    f"🔗 [Full Notice]({notice['url']})\n"
                    f"⏰ {self.get_time()}\n"
                    f"#WBSU #Notice"
                )
                
                # Send to all channels
                for chat_id in GROUP_IDS + [CHAT_ID]:
                    self.send_telegram(chat_id, message)
                
                # Mark as sent
                self.sent_notices["notices"][notice["id"]] = {
                    "sent_time": self.get_time(),
                    "summary": summary
                }
                
                # Small delay to avoid rate limits
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Failed to process notice: {e}", exc_info=True)

    # Continuous monitoring with smart intervals
    def run_monitor(self):
        while True:
            start_time = time.time()
            self.last_check = self.get_time()
            
            try:
                logger.info("Starting monitoring cycle...")
                
                for site in URLS:
                    new_notices = self.monitor_website(site)
                    if new_notices:
                        self.process_notices(site, new_notices)
                        self.save_data(SENT_NOTICES_FILE, self.sent_notices)
                
                # Adaptive sleep based on processing time
                elapsed = time.time() - start_time
                sleep_time = max(10, CHECK_INTERVAL - elapsed)
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Monitoring cycle failed: {e}", exc_info=True)
                time.sleep(60)  # Wait longer on critical errors

    # Enhanced message handling with context
    def handle_message(self, message):
        chat_id = str(message.get("chat", {}).get("id"))
        text = message.get("text", "").strip()
        user_id = str(message.get("from", {}).get("id"))
        
        if not text:
            return
            
        # Update user stats
        self.user_data["users"][user_id] = {
            "last_active": self.get_time(),
            "message_count": self.user_data["users"].get(user_id, {}).get("message_count", 0) + 1
        }
        
        # Command processing
        if text.startswith("/"):
            cmd = text.split()[0].lower()
            
            if cmd == "/start":
                reply = (
                    "🫂 **WBSU Notice Bot v2.0**\n\n"
                    "Mai WBSU ke sabhi updates real-time bhejta hoon!\n\n"
                    "🔹 /notice - Latest updates\n"
                    "🔹 /status - Bot ki condition\n"
                    "🔹 /help - Madad chahiye?\n"
                    "🔹 /feedback - Apna suggestion do"
                )
                
            elif cmd == "/notice":
                self.send_telegram(chat_id, "Checking updates...")
                threading.Thread(target=self.run_monitor).start()
                return
                
            elif cmd == "/status":
                reply = (
                    f"🤖 **Bot Status**\n\n"
                    f"• Last check: {self.last_check or 'N/A'}\n"
                    f"• Websites: {len(URLS)}\n"
                    f"• Notices sent: {len(self.sent_notices.get('notices', {}))}\n"
                    f"• Active users: {len(self.user_data.get('users', {}))}"
                )
                
            elif cmd == "/help":
                reply = (
                    "Koi problem ho toh seedha batao!\n\n"
                    "Agar notice nahi mil raha ho toh /notice try karo.\n\n"
                    "Bot owner: @YourContact"
                )
                
            elif cmd == "/feedback":
                reply = "Apna feedback yahan bhejo: @YourContact\nShukriya!"
                
            else:
                reply = "Ye command nahi samjha! /help dekho"
                
        else:
            # AI-powered conversational replies
            prompt = (
                f"User ({user_id}) ne kaha: '{text}'\n\n"
                f"Context: You're WBSU Notice Bot. Reply in friendly Romazid Hindi (Hinglish). "
                f"Keep it short (1-2 lines). If notice-related, suggest /notice."
            )
            
            reply = self.ask_groq(prompt) or "Samjha nahi, /help try karo"
        
        self.send_telegram(chat_id, reply)

    # Advanced polling with error recovery
    def telegram_polling(self):
        offset = None
        while True:
            try:
                response = requests.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": 30,
                        "allowed_updates": ["message", "callback_query"]
                    },
                    timeout=40
                ).json()
                
                if not response.get("ok"):
                    logger.error(f"Telegram API error: {response}")
                    time.sleep(10)
                    continue
                
                for update in response.get("result", []):
                    offset = update["update_id"] + 1
                    
                    # Handle different update types
                    if "message" in update:
                        self.handle_message(update["message"])
                    elif "callback_query" in update:
                        # Future: Add button support
                        pass
                
            except Exception as e:
                logger.error(f"Polling error: {e}", exc_info=True)
                time.sleep(15)

# Initialize and run
bot = AdvancedNoticeBot()

@app.route('/')
def home():
    return "🤖 WBSU Advanced Notice Bot is Running"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.json
        if "message" in update:
            bot.handle_message(update["message"])
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return 'OK'

def run_bot():
    # Start monitoring thread
    monitor_thread = threading.Thread(target=bot.run_monitor, daemon=True)
    monitor_thread.start()
    
    # Start polling thread
    polling_thread = threading.Thread(target=bot.telegram_polling, daemon=True)
    polling_thread.start()
    
    # Run Flask app
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == '__main__':
    run_bot()