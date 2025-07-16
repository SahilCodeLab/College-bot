import os
import requests
import hashlib
import json
import re
import threading
import time
from datetime import datetime
import pytz
from flask import Flask
from bs4 import BeautifulSoup

app = Flask(__name__)

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///data.db')  # For Render PostgreSQL
CHECK_INTERVAL = 300  # 5 minutes

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
        "name": "BRS College",
        "url": "https://brsnc.in/",
        "selectors": {
            "container": "div#notices",
            "items": "li a"
        }
    }
]

class NoticeBot:
    def __init__(self):
        self.last_checked = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "WBSU Notice Bot v4.0"})
        
        # Initialize database
        if DATABASE_URL.startswith('postgres'):
            import psycopg2
            self.conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        else:
            import sqlite3
            self.conn = sqlite3.connect('data.db')
        
        self._init_db()

    def _init_db(self):
        cur = self.conn.cursor()
        # Create tables if not exists
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            source TEXT,
            semesters TEXT,
            timestamp TEXT
        )""")
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            semesters TEXT,
            last_active TEXT
        )""")
        self.conn.commit()

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
        self.last_checked = self._get_current_time()
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
                    cur = self.conn.cursor()
                    cur.execute("SELECT 1 FROM notices WHERE id = ?", (notice_id,))
                    if cur.fetchone():
                        continue
                    
                    # Detect relevant semesters
                    relevant_sems = []
                    for sem, data in SEMESTERS.items():
                        if any(re.search(rf'\b{kw}\b', title.lower()) for kw in data['keywords']):
                            relevant_sems.append(sem)
                    
                    if not relevant_sems:
                        continue
                    
                    # Generate AI summary
                    summary = self.generate_ai_summary(title) or title
                    
                    # Save to database
                    cur.execute(
                        "INSERT INTO notices VALUES (?, ?, ?, ?, ?, ?)",
                        (notice_id, title, url, source['name'], ','.join(relevant_sems), self._get_current_time())
                    )
                    self.conn.commit()
                    
                    new_notices.append({
                        "id": notice_id,
                        "title": title,
                        "url": url,
                        "source": source['name'],
                        "sems": relevant_sems,
                        "summary": summary
                    })
                    
            except Exception as e:
                print(f"Error checking {source['name']}: {e}")
        
        return new_notices

    def notify_users(self, notices):
        for notice in notices:
            # Find users subscribed to any of the relevant semesters
            cur = self.conn.cursor()
            cur.execute("""
                SELECT user_id FROM users 
                WHERE semesters LIKE ? 
                OR semesters LIKE ? 
                OR semesters LIKE ?
            """, (
                f"%{notice['sems'][0]}%",
                f"%,{notice['sems'][0]}%",
                f"%{notice['sems'][0]},%"
            ))
            
            users = [row[0] for row in cur.fetchall()]
            
            # Prepare message
            sem_names = [SEMESTERS[sem]['name'] for sem in notice['sems']]
            message = (
                f"📢 *{notice['source']} Update*\n"
                f"🎓 *For:* {', '.join(sem_names)}\n\n"
                f"{notice['summary']}\n\n"
                f"🔗 [View Notice]({notice['url']})\n"
                f"⏰ {notice['timestamp']}"
            )
            
            # Send to all subscribed users
            for user_id in users:
                self.send_telegram_message(user_id, message)
                
            # Small delay to avoid rate limits
            time.sleep(0.5)

    def handle_command(self, user_id, command):
        command = command.lower().strip()
        response = None
        
        if command == '/start':
            response = (
                "🫂 *WBSU Notice Bot v4.0*\n\n"
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
                cur = self.conn.cursor()
                cur.execute("SELECT semesters FROM users WHERE user_id = ?", (user_id,))
                result = cur.fetchone()
                
                current_sems = set(result[0].split(',')) if result else set()
                
                if sem in current_sems:
                    current_sems.remove(sem)
                    action = "removed from"
                else:
                    current_sems.add(sem)
                    action = "added to"
                
                # Update database
                cur.execute(
                    "INSERT OR REPLACE INTO users VALUES (?, ?, ?)",
                    (user_id, ','.join(current_sems), self._get_current_time())
                self.conn.commit()
                
                response = f"✅ You've been {action} {SEMESTERS[sem]['name']} updates!"
            else:
                response = "❌ Invalid semester. Use /semlist to see options"
                
        elif command == '/mysems':
            cur = self.conn.cursor()
            cur.execute("SELECT semesters FROM users WHERE user_id = ?", (user_id,))
            result = cur.fetchone()
            
            if result and result[0]:
                sems = [SEMESTERS[sem]['name'] for sem in result[0].split(',')]
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
            # AI-generated response for unknown commands
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
    return "🤖 WBSU Notice Bot v4.0 is running!"

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