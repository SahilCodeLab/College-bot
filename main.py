import threading
import time
import requests
from bs4 import BeautifulSoup
import json
import os
import urllib3
from flask import Flask

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Telegram Bot Details
BOT_TOKEN = '8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo'
CHAT_ID = '6668744108'

# Flask app for port binding (Render requirement)
app = Flask(__name__)

@app.route('/')
def home():
    return "WBSU Bot is running!"

def get_2nd_sem_update():
    url = "https://www.wbsuexams.net/"
    r = requests.get(url, verify=False)
    soup = BeautifulSoup(r.text, 'html.parser')
    for link in soup.find_all('a'):
        text = link.text.strip()
        href = link.get('href')
        if "2nd Semester" in text or "II Semester" in text:
            return f"{text}\n🔗 Link: {href}"
    return None

def load_last():
    if os.path.exists("last_notice.json"):
        with open("last_notice.json", "r") as f:
            return json.load(f).get("notice")
    return ""

def save_notice(notice):
    with open("last_notice.json", "w") as f:
        json.dump({"notice": notice}, f)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

# Run this in background thread
def run_bot_forever():
  send_telegram("✅ Bot test message from Sahil 🚀")
    while True:
        try:
            new_notice = get_2nd_sem_update()
            old_notice = load_last()
            if new_notice and new_notice != old_notice:
                send_telegram("📢 *New 2nd Semester Update Found:*\n\n" + new_notice)
                save_notice(new_notice)
            else:
                print("✅ No update yet.")
        except Exception as e:
            print("❌ Error:", e)
        time.sleep(600)

# Start both Flask and Bot
if __name__ == '__main__':
    threading.Thread(target=run_bot_forever).start()
    app.run(host='0.0.0.0', port=10000)