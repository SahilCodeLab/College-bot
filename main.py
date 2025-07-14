
import requests
from bs4 import BeautifulSoup
import json
import os

BOT_TOKEN = '8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo'
CHAT_ID = '6668744108'  # Replace with your actual chat_id

def get_2nd_sem_update():
    url = "https://www.wbsuexams.net/"
    r = requests.get(url)
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
    data = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, data=data)

def main():
    new_notice = get_2nd_sem_update()
    old_notice = load_last()
    if new_notice and new_notice != old_notice:
        send_telegram("📢 *New 2nd Semester Update Found:*\n\n" + new_notice)
        save_notice(new_notice)
    else:
        print("No new update.")

if __name__ == "__main__":
    main()