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
GROQ_API_KEY = os.environ.get('GROQ_API_KEY') # <<< NEW: For the bot's "brain"

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
    # <<< MODIFIED: This is now a "tool"
    logger.info(f"Using general search tool for: {query}")
    # This is the same search function as before
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
    # <<< NEW: Placeholder for the syllabus scraper tool
    logger.info(f"Using syllabus tool for: {subject} Sem {semester}")
    # Yahan hum syllabus dhoondne ka code likhenge. Abhi ke liye placeholder:
    return f"Syllabus for *{subject} (Semester {semester})* abhi uplabdh nahi hai. Main is feature par kaam kar raha hoon."

def check_results(semester):
    # <<< NEW: Placeholder for the result checker tool
    logger.info(f"Using result checker tool for: Sem {semester}")
    # Yahan hum result check karne ka code likhenge. Abhi ke liye placeholder:
    return f"Semester {semester} ka result abhi tak nahi aaya hai. Jaise hi aayega, main update karunga."

def conversational_chat(user_message):
    # <<< NEW: Tool for general chat
    logger.info("Using conversational chat tool")
    if "hii" in user_message.lower() or "hello" in user_message.lower():
        return "Hello! Main WBSU Assistant. Aapki kya sahayata kar sakta hoon?"
    return "Main aapki baat samajh nahi paya. Aap syllabus, result, ya notices ke baare mein pooch sakte hain."

# --- The "Brain" of the Bot (LLM Router) ---

def get_intent_from_llm(user_text):
    # <<< NEW: This is the core logic that understands the user
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY not set!")
        return {"tool": "error", "message": "AI model theek se configure nahi hai."}

    system_prompt = """
    You are a helpful assistant for a West Bengal State University (WBSU) bot.
    Your job is to understand the user's request and decide which tool to use.
    The user is a student who speaks Hinglish.

    Here are the available tools:
    1. 'get_syllabus': Use this if the user is asking for a syllabus for a specific subject and semester.
    2. 'check_result': Use this if the user is asking about exam results for a specific semester.
    3. 'general_search': Use this for any other specific information request about WBSU (like notices, admission, etc.).
    4. 'chat': Use this for general greetings (hi, hello) or conversational messages that are not asking for information.

    You must respond in JSON format with the chosen "tool" and the "parameters" extracted from the user's text.
    For example:
    User: "3rd sem history syllabus ka pdf hai?" -> {"tool": "get_syllabus", "parameters": {"subject": "History", "semester": "3"}}
    User: "wbsu 2nd sem result kab aayega" -> {"tool": "check_result", "parameters": {"semester": "2"}}
    User: "latest notice" -> {"tool": "general_search", "parameters": {"query": "latest notice"}}
    User: "hello" -> {"tool": "chat", "parameters": {}}
    """

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()
        intent_data = response.json()['choices'][0]['message']['content']
        return json.loads(intent_data)
    except Exception as e:
        logger.error(f"LLM intent error: {e}")
        # Fallback to general search if LLM fails
        return {"tool": "general_search", "parameters": {"query": user_text}}

# --- MODIFIED Main Handler ---

def handle_request(user_id, text):
    # <<< MODIFIED: This is now a router that uses the LLM's brain
    send_telegram_message(user_id, "Soch raha hoon...") # Thinking...

    # Step 1: Understand user's intent
    intent = get_intent_from_llm(text)
    tool_to_use = intent.get("tool")
    parameters = intent.get("parameters", {})
    
    final_response = ""

    # Step 2: Call the appropriate tool based on intent
    if tool_to_use == "get_syllabus":
        final_response = scrape_syllabus(parameters.get("subject", "N/A"), parameters.get("semester", "N/A"))
    elif tool_to_use == "check_result":
        final_response = check_results(parameters.get("semester", "N/A"))
    elif tool_to_use == "general_search":
        final_response = general_search(parameters.get("query", text))
    elif tool_to_use == "chat":
        final_response = conversational_chat(text)
    elif tool_to_use == "error":
        final_response = intent.get("message")
    else:
        final_response = "Main aapki request samajh nahi paya. Main general search kar raha hoon."
        final_response += "\n" + general_search(text)
        
    # Step 3: Send the final answer to the user
    send_telegram_message(user_id, final_response)
    
    # Optional: Log the interaction to Google Sheets
    # log_update_to_sheet(text, final_response, tool_to_use)

# --- Flask Web Server (No changes needed here) ---

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
