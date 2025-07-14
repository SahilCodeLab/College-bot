import threading import time import requests from bs4 import BeautifulSoup import json import os import urllib3 from flask import Flask from datetime import datetime, timedelta

Disable SSL warnings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ENV config

BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo" CHAT_ID = os.environ.get("CHAT_ID") or "6668744108" GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or "AIzaSyD8VIC30KvQ34TY34wIArmXMOH1uQa73Qo"

Flask setup

app = Flask(name)

@app.route('/') def home(): return "✅ Sahil's Bot is Running"

Send message to Telegram

def send_telegram(chat_id, msg): url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage" data = { "chat_id": chat_id, "text": msg, "parse_mode": "Markdown" } try: requests.post(url, data=data) except: print("❌ Telegram send failed.")

Ask Gemini

def ask_gemini(prompt): headers = { "Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY } data = { "contents": [ {"parts": [{"text": prompt}]} ] } try: r = requests.post( "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent", headers=headers, data=json.dumps(data) ) if r.status_code == 200: return r.json()['candidates'][0]['content']['parts'][0]['text'] else: print("Gemini Error Code:", r.status_code) print("Gemini Response:", r.text) return "❌ Gemini Error." except Exception as e: print("❌ Gemini Exception:", e) return "❌ Gemini Error."

Get latest 2nd sem update

def get_2nd_sem_update(): urls = [ "https://www.wbsuexams.net/", "https://brsnc.in/", "https://sahilcodelab.github.io/wbsu-info/verify.html" ]

KEYWORDS = [
    "2nd semester", "ii semester", "2 semester", "sem 2", "2 sem", "2sem",
    "2-nd semester", "semester 2", "semester two", "second semester",
    "2nd sem", "2 nd semester", "second sem", "sem ii", "sem-2", "sem2",
    "2ndsem", "2ndsem result", "2nd sem result", "result of 2nd semester",
    "wbsu 2nd semester"
]

CURRENT_YEAR = "2025"
RECENT_DAYS = 10

for site in urls:
    try:
        r = requests.get(site, verify=False, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        for link in soup.find_all('a'):
            text = link.text.strip().lower()
            href = link.get('href', '')
            combined = text + " " + href.lower()

            if any(k in text for k in KEYWORDS):
                full_link = href if href.startswith("http") else site + href

                if CURRENT_YEAR in combined:
                    return {"text": link.text.strip(), "link": full_link, "source": site}

                parent = link.find_parent()
                date_text = ""
                if parent:
                    for item in parent.find_all(string=True):
                        if "2024" in item or "2023" in item:
                            break
                        if any(m in item.lower() for m in ["july", "aug", "sept", "2025"]):
                            date_text = item.strip()
                            break

                for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
                    try:
                        parsed_date = datetime.strptime(date_text, fmt)
                        if parsed_date >= datetime.now() - timedelta(days=RECENT_DAYS):
                            return {
                                "text": link.text.strip(),
                                "link": full_link,
                                "source": site
                            }
                    except:
                        continue
    except Exception as e:
        print(f"❌ Error scraping {site}:", e)
return None

Load/save notice

def load_last(): if os.path.exists("last_notice.json"): with open("last_notice.json", "r") as f: return json.load(f).get("notice", "") return ""

def save_notice(text): with open("last_notice.json", "w") as f: json.dump({"notice": text}, f)

Auto notice checker

def check_notice_loop(): send_telegram(CHAT_ID, "🤖 Bot started by Sahil.") while True: try: notice = get_2nd_sem_update() old = load_last() if notice and notice["text"] != old: summary = ask_gemini(notice["text"]) msg = f"📢 New 2nd Semester Notice Found! \n📝 {summary} 🔗 Open Notice 🌐 Source: {notice['source']}" send_telegram(CHAT_ID, msg) save_notice(notice["text"]) else: print("✅ No new update.") except Exception as e: print("❌ Update check failed:", e) time.sleep(300)

Gemini chatbot listener

def telegram_chat_loop(): offset = None while True: try: url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates" params = {"offset": offset, "timeout": 100} res = requests.get(url, params=params).json() for update in res.get("result", []): msg = update.get("message", {}) user_id = msg.get("chat", {}).get("id") text = msg.get("text", "") if text: reply = ask_gemini(text) send_telegram(user_id, reply) offset = update["update_id"] + 1 except Exception as e: print("❌ Telegram chat error:", e) time.sleep(1)

Run bot and server

if name == "main": threading.Thread(target=check_notice_loop).start() threading.Thread(target=telegram_chat_loop).start() app.run(host='0.0.0.0', port=10000)

