import requests
from bs4 import BeautifulSoup
import json
import os
import urllib3

# ✅ Disable SSL warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ✅ Telegram Bot Details
BOT_TOKEN = '8051713350:AAEVZ0fRXLpZTPmNehEWEfVwQcOFXN9GBOo'
CHAT_ID = '6668744108'

# ✅ Check WBSU for 2nd Sem Notice
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

# ✅ Load previously saved notice
def load_last():
    if os.path.exists("last_notice.json"):
        with open("last_notice.json", "r") as f:
            return json.load(f).get("notice")
    return ""

# ✅ Save the new notice
def save_notice(notice):
    with open("last_notice.json", "w") as f:
        json.dump({"notice": notice}, f)

# ✅ Send Telegram message
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

# ✅ Main bot function
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