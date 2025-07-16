
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
CHECK_INTERVAL = 30 if os.environ.get('TEST_MODE') else 300  # 30 sec for testing, 5 min for prod
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

# Semester keywords
SEMESTERS = {
    "1": {"name": "1st Semester", "keywords": ["sem 1", "semester 1", "first sem", "1st semester", "1st sem"]},
    "2": {"name": "2nd Semester", "keywords": ["sem 2", "semester 2", "second sem", "2nd semester", "2nd sem"]},
    "3": {"name": "3rd Semester", "keywords": ["sem 3", "semester 3", "third sem", "3rd semester", "3rd sem"]},
    "4": {"name": "4th Semester", "keywords": ["sem 4", "semester 4", "fourth sem", "4th semester", "4th sem"]},
    "5": {"name": "5th Semester", "keywords": ["sem 5", "semester 5", "fifth sem", "5th semester", "5th sem"]},
    "6": {"name": "6th Semester", "keywords": ["sem 6", "semester 6", "sixth sem", "6th semester", "6th sem", "final semester"]}
}

# Sources
SOURCES = [
    {
        "name": "WBSU Official",
        "url": "https://www.wbsuexams.net/",
        "selectors": {
            "container": "div.notice-board",  # Update if website changes
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

    def _clean_old_notices(self, data):
        cutoff = datetime.now(pytz.timezone('Asia/Kolkata')) - timedelta(days=30)
        data['notices'] = {
            k: v for k, v in data['notices'].items()
            if datetime.strptime(v['timestamp'], "%Y-%m-%d %H:%M:%S") > cutoff
        }
        return data

    def send_telegram_message(self, chat_id, text):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Sent message to {chat_id}: {text[:50]}...")
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return None

    def generate_ai_summary(self, text):
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": "llama3-70b-8192",
                    "messages": [{"role": "user", "content": f"Summarize this in 1 line Hinglish: {text}"}],
                    "temperature": 0.3
                },
                timeout=10
            )
            res.raise_for_status()
            return res.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"AI summary error: {e}")
            return text

    def check_for_updates(self):
        logger.info("Checking for updates...")
        data = self._load_data(NOTICES_FILE)
        new_notices = []

        for source in SOURCES:
            try:
                logger.info(f"Scraping {source['name']} ({source['url']})")
                r = self.session.get(source['url'], timeout=15)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                container = soup.select_one(source['selectors']['container'])

                if not container:
                    logger.warning(f"No container found for {source['name']}")
                    continue

                items = container.select(source['selectors']['items'])
                logger.info(f"Found {len(items)} items in {source['name']}")

                for item in items:
                    if any(ignore in item.get('class', []) for ignore in source['selectors'].get('ignore', [])):
                        continue

                    title = item.get_text(strip=True)
                    href = item.get('href')
                    if not title or not href or len(title) < 5:
                        logger.debug(f"Skipping item: title={title}, href={href}")
                        continue

                    url = href if href.startswith('http') else source['url'].rstrip('/') + '/' + href.lstrip('/')
                    notice_id = hashlib.md5(f"{title}{url}".encode()).hexdigest()
                    if notice_id in data['notices']:
                        logger.debug(f"Notice already exists: {title}")
                        continue

                    title_clean = title.lower().replace('-', ' ').replace('–', ' ')
                    sems = [sem for sem, val in SEMESTERS.items() if any(kw in title_clean for kw in val['keywords'])]
                    if not sems:
                        logger.debug(f"No semesters matched for: {title}")
                        continue

                    summary = self.generate_ai_summary(title)
                    timestamp = self._get_current_time()

                    new_notices.append({
                        "id": notice_id,
                        "title": title,
                        "url": url,
                        "source": source['name'],
                        "sems": sems,
                        "summary": summary,
                        "timestamp": timestamp
                    })

                    data['notices'][notice_id] = {
                        "title": title,
                        "url": url,
                        "source": source['name'],
                        "sems": sems,
                        "timestamp": timestamp
                    }

                    logger.info(f"New notice found: {title} ({source['name']}) for semesters: {sems}")

            except Exception as e:
                logger.error(f"Error checking source {source['name']}: {e}")

        if new_notices:
            data = self._clean_old_notices(data)
            data["last_checked"] = self._get_current_time()
            self._save_data(NOTICES_FILE, data)
            logger.info(f"Found {len(new_notices)} new notices")

        return new_notices

    def notify_users(self, notices):
        users_data = self._load_data(USERS_FILE)
        if not users_data['users']:
            logger.warning("No users subscribed to notifications")
            return

        logger.info(f"Processing {len(notices)} new notices for {len(users_data['users'])} users")
        for notice in notices:
            for user_id, user_info in users_data['users'].items():
                semesters = user_info.get("semesters", [])
                if not semesters:
                    logger.debug(f"User {user_id} has no semester subscriptions")
                    continue
                if any(sem in semesters for sem in notice['sems']):
                    sem_names = [SEMESTERS[s]['name'] for s in notice['sems']]
                    msg = (
                        f"📢 *{notice['source']} Notice*\n"
                        f"🎓 *For:* {', '.join(sem_names)}\n\n"
                        f"{notice['summary']}\n\n"
                        f"🔗 [View Notice]({notice['url']})\n"
                        f"⏰ {notice['timestamp']}"
                    )
                    self.send_telegram_message(user_id, msg)
                    logger.info(f"Notified user {user_id} about notice: {notice['title']}")
                    time.sleep(0.5)

    def handle_command(self, user_id, command):
        command = command.lower().strip()
        response = None
        users_data = self._load_data(USERS_FILE)

        if command == '/start':
            response = (
                "🫂 *WBSU Notice Bot v4.4*\n\n"
                "🔹 /mysems - Your subscriptions\n"
                "🔹 /semlist - All semester commands\n"
                "🔹 /notice - Check for updates\n"
                "🔹 /1_sem_update to /6_sem_update - Latest notice"
            )

        elif command == '/semlist':
            response = "🎓 *Available Semesters:*\n\n" + "\n".join([f"/sem{sem} - {data['name']}" for sem, data in SEMESTERS.items()])

        elif command.startswith('/sem'):
            sem = command[4:].strip()
            if sem in SEMESTERS:
                user_id = str(user_id)
                if user_id not in users_data["users"]:
                    users_data["users"][user_id] = {"semesters": []}
                sems = users_data["users"][user_id]["semesters"]
                if sem in sems:
                    sems.remove(sem)
                    action = "removed"
                else:
                    sems.append(sem)
                    action = "added"
                self._save_data(USERS_FILE, users_data)
                response = f"✅ {SEMESTERS[sem]['name']} {action} successfully!"
            else:
                response = "❌ Invalid semester."

        elif command == '/mysems':
            info = users_data["users"].get(str(user_id), {})
            sems = info.get("semesters", [])
            if sems:
                response = "📚 *Your Subscriptions:*\n" + "\n".join([SEMESTERS[s]['name'] for s in sems])
            else:
                response = "ℹ️ You’re not subscribed yet."

        elif command == '/notice':
            response = "🔄 Checking for updates..."
            threading.Thread(target=self.force_check, daemon=True).start()

        elif re.match(r'^/[1-6]_sem_update$', command):
            sem = command.split('_')[0][1:]
            data = self._load_data(NOTICES_FILE)
            notices = [n for n in data['notices'].values() if sem in n.get("sems", [])]
            if notices:
                latest = sorted(notices, key=lambda n: n['timestamp'], reverse=True)[0]
                response = (
                    f"📢 *Latest Notice for {SEMESTERS[sem]['name']}*\n\n"
                    f"{latest['title']}\n"
                    f"🔗 [View]({latest['url']})\n⏰ {latest['timestamp']}"
                )
            else:
                response = "❌ No recent notice found."

        else:
            data = self._load_data(NOTICES_FILE)
            query = command.lower()
            matches = [n for n in data['notices'].values() if query in n['title'].lower() or query in n.get('summary', '').lower()]
            if matches:
                response = "🔎 *Matching Notices:*\n\n"
                for m in matches[:3]:
                    response += f"• [{m['title']}]({m['url']})\n"
            else:
                ai = self.generate_ai_summary(f"User asked: {command}. Respond as notice assistant.")
                response = ai or "🤖 Sorry, couldn't find anything."

        return response

    def force_check(self):
        new = self.check_for_updates()
        if new:
            logger.info(f"Force check found {len(new)} new notices")
            self.notify_users(new)
        else:
            logger.info("Force check found no new notices")

    def run_scheduled_checks(self):
        while True:
            try:
                logger.info("Scheduled check thread alive")
                new = self.check_for_updates()
                if new:
                    logger.info(f"Scheduled check found {len(new)} new notices")
                    self.notify_users(new)
                else:
                    logger.info("Scheduled check found no new notices")
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
            res = bot.handle_command(user_id, text)
            if res:
                bot.send_telegram_message(msg['chat']['id'], res)
        return 'OK'
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'ERROR', 500

def run_bot():
    if not BOT_TOKEN or not GROQ_API_KEY:
        logger.error("BOT_TOKEN or GROQ_API_KEY not set")
        raise ValueError("Missing BOT_TOKEN or GROQ_API_KEY")
    bot = NoticeBot()
    logger.info("Starting scheduled checks thread")
    threading.Thread(target=bot.run_scheduled_checks, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

if __name__ == '__main__':
    run_bot()