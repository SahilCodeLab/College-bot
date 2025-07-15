# main.py  
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
  
# Disable SSL Warnings  
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  
  
# Config  
BOT_TOKEN = os.environ.get("BOT_TOKEN")  
CHAT_ID = os.environ.get("CHAT_ID")  
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")  
  
SENT_NOTICES_FILE = "sent_notices.json"  
USER_DATA_FILE = "user_data.json"  
CHECK_INTERVAL = 300  # 5 min  
MAX_NOTICES = 5  
  
URLS = [  
    {"url": "https://www.wbsuexams.net/", "name": "WBSU Official"},  
    {"url": "https://sahilcodelab.github.io/wbsu-info/verify.html", "name": "Sahil's Info Hub"}  
]  
  
KEYWORDS = [  
    "2nd semester", "ii semester", "sem 2", "2 sem", "2sem",  
    "semester 2", "second semester", "sem-2", "2ndsem",  
    "result", "notice", "routine", "lab", "practical", "exam", "timetable"  
]  
  
# Logging  
logging.basicConfig(  
    level=logging.INFO,  
    format='%(asctime)s - %(levelname)s - %(message)s',  
    handlers=[logging.StreamHandler()]  
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
            logger.error(f"Error loading {file}: {e}")  
        return default  
  
    def save_data(self, file, data):  
        try:  
            with open(file, 'w') as f:  
                json.dump(data, f, indent=2)  
        except Exception as e:  
            logger.error(f"Error saving {file}: {e}")  
  
    def get_ist_time(self):  
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')  
  
    def send_telegram(self, chat_id, text):  
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"  
        payload = {  
            "chat_id": chat_id,  
            "text": text,  
            "parse_mode": "Markdown",  
            "disable_web_page_preview": True  
        }  
        try:  
            r = requests.post(url, json=payload, timeout=10)  
            if not r.json().get("ok"):  
                logger.error(f"Telegram error: {r.text}")  
        except Exception as e:  
            logger.error(f"Send failed: {e}")  
  
    def ask_groq(self, prompt):  
        try:  
            headers = {  
                "Authorization": f"Bearer {GROQ_API_KEY}",  
                "Content-Type": "application/json"  
            }  
            data = {  
                "messages": [{"role": "user", "content": prompt}],  
                "model": "llama3-8b-8192"  
            }  
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data)  
            return res.json()['choices'][0]['message']['content']  
        except Exception as e:  
            logger.error(f"GROQ API error: {e}")  
            return "❌ GROQ failed to summarize."  
  
    def scrape_site(self, site):  
        notices = []  
        try:  
            res = requests.get(site["url"], verify=False, timeout=10)  
            soup = BeautifulSoup(res.text, "html.parser")  
            for link in soup.find_all("a"):  
                text = link.text.strip().lower()  
                href = link.get("href", "")  
                if any(k in text for k in KEYWORDS):  
                    full_link = href if href.startswith("http") else f"{site['url'].rstrip('/')}/{href.lstrip('/')}"  
                    notice = {  
                        "text": link.text.strip(),  
                        "link": full_link,  
                        "source": site["name"],  
                        "timestamp": self.get_ist_time()  
                    }  
                    if notice not in notices:  
                        notices.append(notice)  
        except Exception as e:  
            logger.error(f"Scrape error ({site['name']}): {e}")  
        return notices  
  
    def check_notices(self):  
        self.last_check = self.get_ist_time()  
        new_notices = []  
        for site in URLS:  
            site_notices = self.scrape_site(site)  
            for notice in site_notices:  
                if notice['text'] not in self.sent_notices['notices']:  
                    summary = self.ask_groq(f"Summarize: {notice['text']}")  
                    msg = (  
                        f"📢 *{notice['source']} Notice*\n\n"  
                        f"📝 *{summary}*\n\n"  
                        f"🔗 [View Notice]({notice['link']})\n"  
                        f"🕒 {notice['timestamp']}"  
                    )  
                    self.send_telegram(CHAT_ID, msg)  
                    new_notices.append(notice['text'])  
        if new_notices:  
            self.sent_notices['notices'].extend(new_notices)  
            self.save_data(SENT_NOTICES_FILE, self.sent_notices)  
            logger.info(f"✅ {len(new_notices)} new notice(s) sent!")  
  
    def handle_command(self, chat_id, command):  
        command = command.lower().strip()  
        if str(chat_id) not in self.user_data["users"]:  
            self.user_data["users"][str(chat_id)] = {"first_seen": self.get_ist_time()}  
        self.user_data["users"][str(chat_id)]["last_active"] = self.get_ist_time()  
        self.save_data(USER_DATA_FILE, self.user_data)  
  
        if command == "/start":  
            msg = (  
                "👋 *Welcome to WBSU Notice Bot!*\n\n"  
                "I check notices for 2nd semester updates every 5 min.\n\n"  
                "📌 Commands:\n"  
                "`/notice` - Get latest notices\n"  
                "`/status` - Bot status\n"  
                "`/help` - Show help again"  
            )  
            self.send_telegram(chat_id, msg)  
  
        elif command == "/notice":  
            found = False  
            for site in URLS:  
                notices = self.scrape_site(site)  
                for n in notices[:MAX_NOTICES]:  
                    summary = self.ask_groq(f"Summarize: {n['text']}")  
                    msg = (  
                        f"📌 *{n['source']}*\n\n📝 {summary}\n\n🔗 [View]({n['link']})"  
                    )  
                    self.send_telegram(chat_id, msg)  
                    found = True  
            if not found:  
                self.send_telegram(chat_id, "📭 No latest notices right now.")  
  
        elif command == "/status":  
            msg = (  
                f"🤖 *Status Report*\n\n"  
                f"✅ Working\n"  
                f"🕒 Last Check: {self.last_check or 'N/A'}\n"  
                f"📚 Notices Stored: {len(self.sent_notices['notices'])}\n"  
                f"👥 Users: {len(self.user_data['users'])}"  
            )  
            self.send_telegram(chat_id, msg)  
  
        elif command == "/help":  
            self.handle_command(chat_id, "/start")  
  
        else:  
            reply = self.ask_groq(f"Explain what user means: {command}")  
            self.send_telegram(chat_id, reply)  
  
    def polling_loop(self):  
        offset = None  
        while True:  
            try:  
                res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": offset}, timeout=30).json()  
                for upd in res.get("result", []):  
                    offset = upd["update_id"] + 1  
                    msg = upd.get("message", {})  
                    chat_id = msg.get("chat", {}).get("id")  
                    text = msg.get("text", "").strip()  
                    if text:  
                        self.handle_command(chat_id, text)  
            except Exception as e:  
                logger.error(f"Polling error: {e}")  
                time.sleep(10)  
  
bot = NoticeBot()  
  
@app.route('/')  
def home():  
    return "🤖 WBSU Bot is live"  
  
@app.route('/webhook', methods=['POST'])  
def webhook():  
    update = request.json  
    if 'message' in update:  
        chat_id = update['message']['chat']['id']  
        text = update['message'].get('text', '')  
        if text:  
            bot.handle_command(chat_id, text)  
    return 'ok', 200  
  
def run_bot():  
    threading.Thread(target=bot.check_notices, daemon=True).start()  
    threading.Thread(target=bot.polling_loop, daemon=True).start()  
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))  
  
if __name__ == '__main__':  
    run_bot()