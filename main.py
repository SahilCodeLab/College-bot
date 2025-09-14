import os
import requests
import json
import re
import threading
import time
from datetime import datetime
import pytz
from flask import Flask, request
from bs4 import BeautifulSoup
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googlesearch import search

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Configuration ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CREDENTIALS_FILE = 'credentials.json'  # Your Google API credentials

# Google Sheets for logging updates (for your frontend)
# IMPORTANT: Use a DIFFERENT Sheet ID than your user data sheet
UPDATES_SPREADSHEET_ID = os.environ.get('UPDATES_SPREADSHEET_ID')

# --- Helper Functions ---

def get_current_time():
    """Returns the current time in IST."""
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M:%S")

def init_google_sheets():
    """Initializes and returns the Google Sheets client."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        logger.info("Successfully connected to Google Sheets.")
        return client
    except Exception as e:
        logger.error(f"Google Sheets initialization error: {e}")
        return None

# Initialize Google Sheets client globally
gc = init_google_sheets()

# --- Core Bot Functions ---

def send_telegram_message(chat_id, text):
    """Sends a message to a given Telegram chat ID."""
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Message sent to {chat_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")

def realtime_wbsu_search(query):
    """
    Performs a real-time search on the WBSU website using Google Search
    and returns the top result's title and URL.
    """
    logger.info(f"Performing real-time search for: {query}")
    try:
        # We add "site:wbsu.ac.in" or "site:wbsuexams.net" to limit search to the university sites
        search_query = f"{query} site:wbsu.ac.in OR site:wbsuexams.net"
        
        # googlesearch-python library returns a generator
        search_results = search(search_query, num=1, stop=1, pause=2)
        
        top_result_url = next(search_results, None)

        if not top_result_url:
            logger.warning(f"No search results found for query: {query}")
            return None, "Is vishay par koi jaankari nahi mili.", None

        # Scrape the page title for a better summary
        response = requests.get(top_result_url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.string.strip() if soup.title else "Result Page"

        return title, f"Mili jaankari ke anusaar:\n\n*Title:* {title}\n\n*Link:* {top_result_url}", top_result_url

    except Exception as e:
        logger.error(f"Error during real-time search for '{query}': {e}")
        return None, "Search karte samay ek samasya aa gayi. Kripya baad mein prayas karein.", None

def log_update_to_sheet(topic, details, link):
    """
    Logs the new information found into a dedicated Google Sheet.
    This sheet can be used by your frontend.
    """
    if not gc or not UPDATES_SPREADSHEET_ID:
        logger.error("Google Sheets client or UPDATES_SPREADSHEET_ID not configured. Cannot log update.")
        return

    try:
        sheet = gc.open_by_key(UPDATES_SPREADSHEET_ID).sheet1
        
        # Ensure header row exists
        if sheet.cell(1, 1).value != 'Timestamp':
             sheet.insert_row(['Timestamp', 'Topic/Query', 'Details', 'Source Link'], 1)

        row_to_add = [get_current_time(), topic, details, link]
        sheet.append_row(row_to_add)
        logger.info(f"Successfully logged new update to sheet: {topic}")
    except Exception as e:
        logger.error(f"Failed to log update to Google Sheet: {e}")

def handle_request(user_id, text):
    """Handles incoming user messages."""
    
    # Simple command handling
    if text.lower().strip() == '/start':
        response_text = (
            "Namaste! 🙏\n"
            "Main WBSU ka real-time information bot hoon.\n\n"
            "Aap kisi bhi semester, subject, ya topic (jaise '3rd sem zoology syllabus' ya 'latest exam notice') ke baare mein sawaal pooch sakte hain."
        )
        send_telegram_message(user_id, response_text)
        return

    # Treat any other message as a real-time query
    send_telegram_message(user_id, f"🔄 Aapke sawaal '{text}' ke liye WBSU website par jaankari dhoond raha hoon...")
    
    title, response_text, url = realtime_wbsu_search(text)
    
    send_telegram_message(user_id, response_text)

    # If a valid result was found, log it to the Google Sheet for the frontend
    if url:
        # We pass the original query as the topic
        log_update_to_sheet(topic=text, details=title, link=url)


# --- Flask Web Server ---

@app.route('/')
def home():
    return "WBSU Real-time Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.json
        if 'message' in update and 'text' in update['message']:
            user_id = update['message']['chat']['id']
            text = update['message']['text']
            
            # Run the handler in a separate thread to avoid Telegram timeouts
            threading.Thread(target=handle_request, args=(user_id, text)).start()
            
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
    
    return "OK", 200

def run_bot():
    if not BOT_TOKEN or not UPDATES_SPREADSHEET_ID:
        raise ValueError("BOT_TOKEN and UPDATES_SPREADSHEET_ID environment variables must be set.")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

if __name__ == '__main__':
    run_bot()

