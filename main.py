import os
import requests
import hashlib
import json
import re
import threading
import time
from datetime import datetime
import pytz
from flask import Flask, request
from bs4 import BeautifulSoup

app = Flask(__name__)

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CHECK_INTERVAL = 300  # 5 minutes
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
NOTICES_FILE = os.path.join(DATA_DIR, 'notices.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# Initialize data files
def init_data_files():
    defaults = {
        NOTICES_FILE: {"notices": {}, "last_checked": None},
        USERS_FILE: {"users": {}}
    }
    for file, default in defaults.items():
        if not os.path.exists(file):
            with open(file, 'w') as f:
                json.dump(default, f)

init_data_files()

# Semester configuration
SEMESTERS = {
    "1": {"name": "1st Semester", "keywords": ["sem 1", "semester 1", "first sem"]},
    "2": {"name": "2nd Semester", "keywords": ["sem 2", "semester 2", "second sem"]},
    "3": {"name": "3rd Semester", "keywords": ["sem 3", "semester 3", "third sem"]},
    "4": {"name": "4th Semester", "keywords": ["sem 4", "semester 4", "fourth sem"]},
    "5": {"name": "5th Semester", "keywords": ["sem 5", "semester 5", "fifth sem"]},
    "6": {"name": "6th Semester", "keywords": ["sem 6", "semester 6", "sixth sem"]}
}

# Websites to monitor
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
        "name": "Sahil's Test Hub",
        "url": "https://sahilcodelab.github.io/wbsu-info/verify.html",
        "selectors": {
            "container": "body",   # Since all <a> are directly in <body>
            "items": "a",
            "ignore": []
        }
    },
    {
        "name": "WBSU Main Website",
        "url": "https://wbsu.ac.in/web/",
        "selectors": {
            "container": "div.elementor-widget-container",  # Common container for links
            "items": "a",
            "ignore": []
        }
    },
    {
        "name": "WBSU NEP Syllabus",
        "url": "https://wbsu.ac.in/web/nep-syllabus/",
        "selectors": {
            "container": "div.elementor-widget-container",  # Same structure
            "items": "a",
            "ignore": []
        }
    }
]

class NoticeBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "WBSU Notice Bot v4.1"})
        self.lock = threading.Lock()

    def _load_data(self, file):
        with self.lock:
            with open(file, 'r') as f:
                return json.load(f)

    def _save_data(self, file, data):
        with self.lock:
            with open(file, 'w') as f:
                json.dump(data, f, indent=2)

    def _get_current_time(self):
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M:%S")

    def send_telegram_message(self, chat_id, text):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            return response.json()
        except Exception as e:
            print(f"Error sending message: {e}")
            return None

    def generate_ai_summary(self, text):
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": "llama3-70b-8192",
                    "messages": [{
                        "role": "user",
                        "content": f"Summarize this notice in 1 line Hinglish: {text}"
                    }],
                    "temperature": 0.3
                },
                timeout=15
            )
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"AI error: {e}")
            return None

    def check_for_updates(self):
        data = self._load_data(NOTICES_FILE)
        new_notices = []
        
        for source in SOURCES:
            try:
                response = self.session.get(source['url'], timeout=15)
                soup = BeautifulSoup(response.text, 'html.parser')
                container = soup.select_one(source['selectors']['container'])
                
                if not container:
                    continue
                    
                for item in container.select(source['selectors']['items']):
                    if any(ignore in item.get('class', []) for ignore in source['selectors'].get('ignore', [])):
                        continue
                        
                    title = item.get_text(strip=True)
                    url = item['href'] if item['href'].startswith('http') else f"{source['url'].rstrip('/')}/{item['href'].lstrip('/')}"
                    
                    if not title or len(title) < 10:
                        continue
                        
                    # Check if notice exists
                    notice_id = hashlib.md5(f"{title}{url}".encode()).hexdigest()
                    if notice_id in data["notices"]:
                        continue
                    
                    # Detect relevant semesters
                    relevant_sems = []
                    for sem, sem_data in SEMESTERS.items():
                        if any(re.search(rf'\b{kw}\b', title.lower()) for kw in sem_data['keywords']):
                            relevant_sems.append(sem)
                    
                    if not relevant_sems:
                        continue
                    
                    # Generate AI summary
                    summary = self.generate_ai_summary(title) or title
                    timestamp = self._get_current_time()
                    
                    # Add to new notices
                    new_notices.append({
                        "id": notice_id,
                        "title": title,
                        "url": url,
                        "source": source['name'],
                        "sems": relevant_sems,
                        "summary": summary,
                        "timestamp": timestamp
                    })
                    
                    # Update notices data
                    data["notices"][notice_id] = {
                        "title": title,
                        "url": url,
                        "source": source['name'],
                        "sems": relevant_sems,
                        "timestamp": timestamp
                    }
                    
            except Exception as e:
                print(f"Error checking {source['name']}: {e}")
        
        if new_notices:
            data["last_checked"] = self._get_current_time()
            self._save_data(NOTICES_FILE, data)
        
        return new_notices

    def notify_users(self, notices):
        users_data = self._load_data(USERS_FILE)
        
        for notice in notices:
            try:
                # Find subscribed users
                subscribers = []
                for user_id, user_info in users_data["users"].items():
                    if any(sem in user_info.get("semesters", []) for sem in notice["sems"]):
                        subscribers.append(user_id)
                
                if not subscribers:
                    continue
                
                # Prepare message
                sem_names = [SEMESTERS[sem]['name'] for sem in notice["sems"]]
                message = (
                    f"📢 *{notice['source']} Update*\n"
                    f"🎓 *For:* {', '.join(sem_names)}\n\n"
                    f"{notice['summary']}\n\n"
                    f"🔗 [View Notice]({notice['url']})\n"
                    f"⏰ {notice['timestamp']}"
                )
                
                # Send to subscribers
                for user_id in subscribers:
                    self.send_telegram_message(user_id, message)
                    time.sleep(0.3)  # Rate limiting
                    
            except Exception as e:
                print(f"Error notifying users: {e}")

    def handle_command(self, user_id, command):
        command = command.lower().strip()
        response = None
        users_data = self._load_data(USERS_FILE)
        
        if command == '/start':
            response = (
                "🫂 *WBSU Notice Bot v4.1*\n\n"
                "🔹 /mysems - Your current subscriptions\n"
                "🔹 /semlist - Show all semester commands\n"
                "🔹 /notice - Check for updates now\n"
                "🔹 /help - Get assistance"
            )
            
        elif command == '/semlist':
            sem_list = "\n".join([f"/sem{sem} - {data['name']}" for sem, data in SEMESTERS.items()])
            response = f"🎓 *Available Semesters:*\n\n{sem_list}"
            
        elif command.startswith('/sem'):
            sem = command[4:].strip()
            if sem in SEMESTERS:
                user_id = str(user_id)
                if user_id not in users_data["users"]:
                    users_data["users"][user_id] = {"semesters": []}
                
                current_sems = users_data["users"][user_id]["semesters"]
                
                if sem in current_sems:
                    current_sems.remove(sem)
                    action = "removed from"
                else:
                    current_sems.append(sem)
                    action = "added to"
                
                self._save_data(USERS_FILE, users_data)
                response = f"✅ You've been {action} {SEMESTERS[sem]['name']} updates!"
            else:
                response = "❌ Invalid semester. Use /semlist to see options"
                
        elif command == '/mysems':
            user_info = users_data["users"].get(str(user_id), {})
            if user_info.get("semesters"):
                sems = [SEMESTERS[sem]['name'] for sem in user_info["semesters"] if sem in SEMESTERS]
                response = f"📚 *Your Subscriptions:*\n\n" + "\n".join(sems)
            else:
                response = "ℹ️ You're not subscribed to any semesters. Use /sem1 to /sem6 to subscribe"
                
        elif command == '/notice':
            response = "🔄 Checking for updates... New notices will appear here shortly!"
            threading.Thread(target=self.force_check).start()
            
        elif command == '/help':
            response = (
                "Need help? Here's what you can do:\n\n"
                "• Subscribe to semester updates with /sem1 to /sem6\n"
                "• Check your current subscriptions with /mysems\n"
                "• Force an update check with /notice\n\n"
                "For further assistance, contact @YourContact"
            )
            
        else:
            ai_response = self.generate_ai_summary(
                f"User sent: '{command}'. Respond as a helpful university notice bot in Hinglish"
            )
            response = ai_response or "Sorry, I didn't understand that. Try /help"
            
        return response

    def force_check(self):
        new_notices = self.check_for_updates()
        if new_notices:
            self.notify_users(new_notices)

    def run_scheduled_checks(self):
        while True:
            new_notices = self.check_for_updates()
            if new_notices:
                self.notify_users(new_notices)
            time.sleep(CHECK_INTERVAL)

@app.route('/')
def home():
    return "🤖 WBSU Notice Bot v4.1 is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.json
        if 'message' in update:
            message = update['message']
            user_id = str(message['from']['id'])
            text = message.get('text', '')
            
            bot = NoticeBot()
            response = bot.handle_command(user_id, text)
            
            if response:
                bot.send_telegram_message(message['chat']['id'], response)
                
    except Exception as e:
        print(f"Webhook error: {e}")
        
    return 'OK'

def run_bot():
    bot = NoticeBot()
    
    # Start background checker
    threading.Thread(target=bot.run_scheduled_checks, daemon=True).start()
    
    # Start Flask app
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

if __name__ == '__main__':
    run_bot()