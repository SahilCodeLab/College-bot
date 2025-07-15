import threading
import time
import requests
import urllib3
from bs4 import BeautifulSoup
import json
import os
from flask import Flask, jsonify
import logging
from datetime import datetime

# Disable warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Constants
SENT_NOTICES_FILE = "sent_notices.json"
CHECK_INTERVAL = 300  # 5 minutes

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def load_sent_notices():
    try:
        if os.path.exists(SENT_NOTICES_FILE):
            with open(SENT_NOTICES_FILE, "r") as f:
                return json.load(f).get("notices", [])
    except Exception as e:
        logger.error(f"Error loading notices: {e}")
    return []

def save_sent_notices(notices):
    try:
        with open(SENT_NOTICES_FILE, "w") as f:
            json.dump({"notices": notices}, f)
    except Exception as e:
        logger.error(f"Error saving notices: {e}")

def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return None

def scrape_site(site_info):
    try:
        response = requests.get(site_info["url"], verify=False, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        notices = []
        
        for link in soup.find_all('a'):
            text = link.text.strip().lower()
            href = link.get('href', '')
            
            if any(keyword in text for keyword in KEYWORDS):
                full_link = href if href.startswith("http") else site_info["url"].rstrip('/') + '/' + href.lstrip('/')
                notices.append({
                    "text": link.text.strip(),
                    "link": full_link,
                    "source": site_info["name"],
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        
        return notices
    except Exception as e:
        logger.error(f"Error scraping {site_info['name']}: {e}")
        return []

def check_notices():
    sent_notices = load_sent_notices()
    all_notices = []
    
    for site in URLS:
        notices = scrape_site(site)
        all_notices.extend(notices)
    
    new_notices = []
    for notice in all_notices:
        if notice["text"] not in sent_notices:
            msg = (
                f"📢 *New Notice Alert!* ({notice['source']})\n\n"
                f"📝 *{notice['text']}*\n\n"
                f"🔗 [View Notice]({notice['link']})\n"
                f"⏰ {notice['time']}"
            )
            send_telegram(CHAT_ID, msg)
            new_notices.append(notice["text"])
    
    if new_notices:
        sent_notices.extend(new_notices)
        save_sent_notices(sent_notices)
        logger.info(f"Sent {len(new_notices)} new notices")

def notice_loop():
    logger.info("Starting notice checking loop")
    while True:
        try:
            check_notices()
        except Exception as e:
            logger.error(f"Error in notice loop: {e}")
        time.sleep(CHECK_INTERVAL)

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "WBSU Notice Bot",
        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    # Start background thread
    threading.Thread(target=notice_loop, daemon=True).start()
    
    # Run Flask app
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)