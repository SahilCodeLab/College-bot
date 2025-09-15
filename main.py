import os
import requests
import json
from flask import Flask, request
from bs4 import BeautifulSoup
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import threading
from datetime import datetime
import pytz

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CREDENTIALS_FILE = 'credentials.json'
UPDATES_SPREADSHEET_ID = os.environ.get('UPDATES_SPREADSHEET_ID')
GOOGLE_SEARCH_API_KEY = os.environ.get('GOOGLE_SEARCH_API_KEY')
GOOGLE_SEARCH_CX = os.environ.get('GOOGLE_SEARCH_CX')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

# --- Google Sheets Initialization ---
def init_google_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Google Sheets initialization error: {e}")
        return None
gc = init_google_sheets()

# --- TOOL FUNCTIONS (Bot ke alag-alag kaam) ---

def general_search(query):
    logger.info(f"Using general search tool for: {query}")
    search_url = "https://www.googleapis.com/customsearch/v1"
    search_query = f"{query} site:wbsu.ac.in OR site:wbsuexams.net"
    params = {'key': GOOGLE_SEARCH_API_KEY, 'cx': GOOGLE_SEARCH_CX, 'q': search_query, 'num': 1}
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        results = response.json()
        if 'items' in results and results['items']:
            item = results['items'][0]
            return f"Mili jaankari ke anusaar:\n\n*Title:* {item.get('title')}\n*Link:* {item.get('link')}"
        return "Is vishay par koi jaankari nahi mili."
    except Exception as e:
        logger.error(f"General search tool error: {e}")
        return "Search karte samay ek takneeki samasya aa gayi."

def scrape_syllabus(subject, semester):
    logger.info(f"Using syllabus tool for: {subject} Sem {semester}")
    try:
        url = "https://wbsu.ac.in/web/nep-syllabus/"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = soup.find_all('a')
        found_links = []
        for link in links:
            link_text = link.get_text().lower()
            if subject.lower() in link_text and semester in link_text and link.get('href', '').endswith('.pdf'):
                found_links.append(f"- [{link.get_text()}]({link.get('href')})")
        
        if found_links:
            return f"*{subject} (Semester {semester})* ke liye yeh syllabus mile hain:\n" + "\n".join(found_links)
        else:
            return f"*{subject} (Semester {semester})* ke liye koi specific PDF syllabus nahi mila. Aap yahan check kar sakte hain: {url}"
            
    except Exception as e:
        logger.error(f"Syllabus scraper error: {e}")
        return "Syllabus dhoondhte samay ek samasya aa gayi."

def check_results(semester):
    logger.info(f"Using result checker tool for: Sem {semester}")
    try:
        url = "https://www.wbsuexams.net/"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        links = soup.find_all('a')
        found_links = []
        for link in links:
            link_text = link.get_text().lower()
            if 'result' in link_text and f'sem' in link_text and semester in link_text:
                full_url = requests.compat.urljoin(url, link.get('href'))
                found_links.append(f"- [{link.get_text()}]({full_url})")

        if found_links:
            return f"*Semester {semester}* ke results se sambandhit yeh links mile hain:\n" + "\n".join(found_links)
        else:
            return f"*Semester {semester}* ka result abhi tak is page par nahi aaya hai. Aap yahan check karte rahein: {url}"

    except Exception as e:
        logger.error(f"Result checker error: {e}")
        return "Result check karte samay ek samasya aa gayi."

def conversational_chat(user_message):
    logger.info("Using conversational chat tool")
    if any(greet in user_message.lower() for greet in ["hii", "hello", "hey", "hi"]):
        return "Hello! Main WBSU Assistant. Aap syllabus, result, ya notices ke baare mein pooch sakte hain."
    return "Main aapki baat samajh nahi paya. Kripya saaf saaf batayein ki aapko kya janna hai."

# --- The "Brain" of the Bot (LLM Router) ---
def get_intent_from_llm(user_text):
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY not set!")
        return {"tool": "error", "message": "AI model theek se configure nahi hai."}

    system_prompt = """You are a helpful assistant for a WBSU bot. Understand the user's Hinglish request and decide which tool to use.
    Tools: 'get_syllabus', 'check_result', 'general_search', 'chat'.
    Respond in JSON with "tool" and "parameters".
    Examples:
    User: "3rd sem history syllabus ka pdf hai?" -> {"tool": "get_syllabus", "parameters": {"subject": "History", "semester": "3"}}
    User: "wbsu 2nd sem result kab aayega" -> {"tool": "check_result", "parameters": {"semester": "2"}}
    User: "latest notice" -> {"tool": "general_search", "parameters": {"query": "latest notice"}}
    User: "hello bhai" -> {"tool": "chat", "parameters": {}}"""
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama3-70b-8192",
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()
        intent_data = response.json()['choices'][0]['message']['content']
        logger.info(f"LLM Intent Detected: {intent_data}")
        return json.loads(intent_data)
    except Exception as e:
        logger.error(f"LLM intent error: {e}")
        return {"tool": "general_search", "parameters": {"query": user_text}}

# --- Main Handler ---
def handle_request(user_id, text):
    send_telegram_message(user_id, "Soch raha hoon...")
    intent = get_intent_from_llm(text)
    tool_to_use = intent.get("tool")
    parameters = intent.get("parameters", {})
    final_response = ""

    if tool_to_use == "get_syllabus":
        final_response = scrape_syllabus(parameters.get("subject", "N/A"), parameters.get("semester", "N/A"))
    elif tool_to_use == "check_result":
        final_response = check_results(parameters.get("semester", "N/A"))
    elif tool_to_use == "general_search":
        final_response = general_search(parameters.get("query", text))
    elif tool_to_use == "chat":
        final_response = conversational_chat(text)
    else:
        final_response = general_search(text)
        
    send_telegram_message(user_id, final_response)

# --- Flask Web Server ---
@app.route('/')
def home(): return "WBSU AI Assistant is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.json
        if 'message' in update and 'text' in update['message']:
            user_id = update['message']['chat']['id']
            text = update['message']['text']
            threading.Thread(target=handle_request, args=(user_id, text)).start()
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
    return "OK", 200

def run_bot():
    if not all([BOT_TOKEN, GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CX, GROQ_API_KEY]):
        raise ValueError("One or more required environment variables are not set.")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

if __name__ == '__main__':
    run_bot()
