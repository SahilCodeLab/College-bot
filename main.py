import threading
import time
import requests
import hashlib
from bs4 import BeautifulSoup
import json
import os
from flask import Flask
import logging
from datetime import datetime
import pytz
import re
from collections import defaultdict

# Enhanced Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
DATA_DIR = "data"

# Constants
CHECK_INTERVAL = 300  # 5 minutes
SENT_NOTICES_FILE = f"{DATA_DIR}/sent_notices.json"
USER_DATA_FILE = f"{DATA_DIR}/user_data.json"
MAX_CONTENT_LENGTH = 1500

# Semester-wise Keywords
SEMESTER_KEYWORDS = {
    "1": ["1st sem", "semester 1", "sem i", "first sem"],
    "2": ["2nd sem", "semester 2", "sem ii", "second sem"],
    "3": ["3rd sem", "semester 3", "sem iii", "third sem"],
    "4": ["4th sem", "semester 4", "sem iv", "fourth sem"],
    "5": ["5th sem", "semester 5", "sem v", "fifth sem"],
    "6": ["6th sem", "semester 6", "sem vi", "sixth sem"]
}

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
    }
]

class UltimateNoticeBot:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.sent_notices = self.load_data(SENT_NOTICES_FILE, {"notices": {}, "hashes": {}})
        self.user_data = self.load_data(USER_DATA_FILE, {"users": {}, "preferences": {}})
        self.last_check = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "WBSU Notice Bot v3.0"})
        self.lock = threading.Lock()

    def load_data(self, filename, default):
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Load error {filename}: {e}")
        return default

    def save_data(self, filename, data):
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Save error {filename}: {e}")

    def get_time(self):
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%d-%m-%Y %H:%M:%S")

    def send_telegram(self, chat_id, text):
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True
                },
                timeout=10
            )
        except Exception as e:
            logging.error(f"Telegram error: {e}")

    def ask_groq(self, prompt):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-70b-8192",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20
            ).json()
            return response['choices'][0]['message']['content']
        except Exception as e:
            logging.error(f"Groq API error: {e}")
            return None

    def check_semester(self, text, semester):
        keywords = SEMESTER_KEYWORDS.get(semester, [])
        return any(re.search(rf'\b{kw}\b', text.lower()) for kw in keywords)

    def monitor_website(self, site):
        try:
            response = self.session.get(site["url"], timeout=20, verify=False)
            soup = BeautifulSoup(response.text, 'html.parser')
            container = soup.select_one(site["selectors"]["container"]) or soup
            current_hash = hashlib.sha256(str(container).encode()).hexdigest()
            
            if current_hash != self.sent_notices["hashes"].get(site["url"]):
                notices = []
                for element in container.select(site["selectors"]["links"]):
                    text = element.get_text(" ", strip=True)
                    href = element.get('href', '')
                    if not text or len(text) < 10:
                        continue
                        
                    url = href if href.startswith('http') else f"{site['url'].rstrip('/')}/{href.lstrip('/')}"
                    notice_id = hashlib.md5(f"{text}{url}".encode()).hexdigest()
                    
                    if notice_id not in self.sent_notices["notices"]:
                        notices.append({
                            "id": notice_id,
                            "text": text,
                            "url": url,
                            "time": self.get_time()
                        })
                
                if notices:
                    with self.lock:
                        self.sent_notices["hashes"][site["url"]] = current_hash
                        for notice in notices:
                            self.sent_notices["notices"][notice["id"]] = notice
                    return notices
        except Exception as e:
            logging.error(f"Monitoring error {site['name']}: {e}")
        return []

    def process_notices(self, site, notices):
        for notice in notices:
            try:
                # Check which semesters this notice applies to
                relevant_semesters = [
                    sem for sem in SEMESTER_KEYWORDS 
                    if self.check_semester(notice["text"], sem)
                ]
                
                if not relevant_semesters:
                    continue
                
                # Generate summary
                summary = self.ask_groq(
                    f"Summarize this notice in 1 line Hinglish for semesters {','.join(relevant_semesters)}: {notice['text']}"
                ) or notice['text']
                
                # Prepare message
                message = (
                    f"📢 *{site['name']} Update*\n"
                    f"🎓 Semesters: {', '.join(relevant_semesters)}\n\n"
                    f"{summary}\n\n"
                    f"🔗 [Full Notice]({notice['url']})\n"
                    f"⏰ {notice['time']}"
                )
                
                # Send to subscribed users
                for user_id, prefs in self.user_data["preferences"].items():
                    if any(sem in prefs.get("semesters", []) for sem in relevant_semesters):
                        self.send_telegram(user_id, message)
                
                # Send to groups
                for group_id in prefs.get("groups", []):
                    self.send_telegram(group_id, message)
                    
            except Exception as e:
                logging.error(f"Notice processing error: {e}")

    def run_monitor(self):
        while True:
            self.last_check = self.get_time()
            try:
                for site in URLS:
                    notices = self.monitor_website(site)
                    if notices:
                        self.process_notices(site, notices)
                        self.save_data(SENT_NOTICES_FILE, self.sent_notices)
            except Exception as e:
                logging.error(f"Monitoring cycle error: {e}")
            time.sleep(CHECK_INTERVAL)

    def handle_command(self, chat_id, text, user_id):
        text = text.lower().strip()
        
        # Semester selection
        if text.startswith("/sem"):
            sem = text.split()[-1]
            if sem in SEMESTER_KEYWORDS:
                with self.lock:
                    if "preferences" not in self.user_data:
                        self.user_data["preferences"] = {}
                    if user_id not in self.user_data["preferences"]:
                        self.user_data["preferences"][user_id] = {"semesters": []}
                    
                    if sem in self.user_data["preferences"][user_id]["semesters"]:
                        self.user_data["preferences"][user_id]["semesters"].remove(sem)
                        reply = f"Semester {sem} updates turned off ✅"
                    else:
                        self.user_data["preferences"][user_id]["semesters"].append(sem)
                        reply = f"Semester {sem} updates activated! 🎓"
                    
                    self.save_data(USER_DATA_FILE, self.user_data)
            else:
                reply = "Invalid semester! Use /sem 1 to /sem 6"
        
        # Normal commands
        elif text == "/start":
            reply = (
                "🫂 *WBSU Notice Bot v3.0*\n\n"
                "🔹 /sem X - Toggle semester updates (1-6)\n"
                "🔹 /notice - Force check updates\n"
                "🔹 /mysems - Your active semesters\n"
                "🔹 /help - Assistance"
            )
        
        elif text == "/notice":
            reply = "Checking updates... New notices will appear here!"
            threading.Thread(target=self.force_check).start()
        
        elif text == "/mysems":
            sems = self.user_data["preferences"].get(user_id, {}).get("semesters", [])
            reply = f"Your active semesters: {', '.join(sems) or 'None'}\nUse /sem X to add"
        
        elif text == "/help":
            reply = (
                "Need help? Contact admin @YourContact\n\n"
                "Pro Tip: Use /sem 2 /sem 4 to track multiple semesters!"
            )
        
        else:
            reply = self.ask_groq(f"User asked: '{text}'. Reply in friendly Hinglish as WBSU Notice Bot") or "Try /help"
        
        self.send_telegram(chat_id, reply)

    def force_check(self):
        for site in URLS:
            notices = self.monitor_website(site)
            if notices:
                self.process_notices(site, notices)
                self.save_data(SENT_NOTICES_FILE, self.sent_notices)

    def telegram_polling(self):
        offset = None
        while True:
            try:
                updates = requests.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 30}
                ).json()
                
                for update in updates.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        msg = update["message"]
                        self.handle_command(
                            chat_id=msg["chat"]["id"],
                            text=msg.get("text", ""),
                            user_id=str(msg["from"]["id"])
                        )
            except Exception as e:
                logging.error(f"Polling error: {e}")
                time.sleep(10)

# Initialize and run
bot = UltimateNoticeBot()

@app.route('/')
def home():
    return "🤖 WBSU Ultimate Notice Bot v3.0"

def run_bot():
    threading.Thread(target=bot.run_monitor, daemon=True).start()
    threading.Thread(target=bot.telegram_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == '__main__':
    run_bot()