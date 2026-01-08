import os
import time
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==========================================
#           CONFIGURATION
# ==========================================
# READ FROM ENVIRONMENT VARIABLES (Secrets)
BOT_TOKEN = os.environ.get("TOKEN")

# REPLACE THIS WITH YOUR NUMERIC TELEGRAM ID
OWNER_USER_ID = int(os.environ.get("OWNER_USER_ID", "0"))

# ADD YOUR SPECIFIC WEBSITE LINKS HERE
# NOTE: Using a specific tag page for LeakVids ensures we get a clean video list.
WEBSITE_URLS = [
    "https://desihub.org/",
    "https://www.desitales2.com/videos/latest-updates/",
    "https://leakvids.com/tags/leaked/" 
]

# HOW OFTEN TO CHECK (in minutes)
CHECK_INTERVAL_MINUTES = 30

# ==========================================
#           SETUP & LOGGING
# ==========================================
app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SEEN_FILE = "seen_videos.txt"

def load_seen_videos():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_seen_video(url):
    """Appends a URL to the seen file (Thread-safe append)."""
    with open(SEEN_FILE, "a") as f:
        f.write(url + "\n")

def escape_markdown(text):
    """Escapes special characters to prevent Telegram Markdown errors."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

# ==========================================
#        SITE-SPECIFIC PARSING
# ==========================================
def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.text
        else:
            logger.warning(f"Status {resp.status_code} for {url}")
            return None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

def parse_videos(url):
    """Dispatches to the correct parser based on the URL."""
    html = fetch_html(url)
    if not html:
        return []

    if "desihub.org" in url:
        return parse_desihub(html, url)
    elif "desitales2.com" in url:
        return parse_desitales2(html, url)
    elif "leakvids.com" in url:
        return parse_leakvids(html, url)
    else:
        logger.warning(f"No parser defined for {url}")
        return []

def parse_desihub(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    videos = []
    items = soup.find_all('li', class_='video-block') 
    if not items:
        items = soup.find_all('div', class_='item')

    for item in items:
        try:
            link_tag = item.find('a', href=True)
            if not link_tag: continue
            
            video_url = link_tag['href']
            if video_url.startswith('//'): video_url = 'https:' + video_url
            elif not video_url.startswith('http'): video_url = base_url.rstrip('/') + '/' + video_url.lstrip('/')

            title = link_tag.get('title', '') or link_tag.img.get('alt', 'No Title')

            img_tag = link_tag.find('img')
            thumb = img_tag['src'] if img_tag and img_tag.has_attr('src') else None
            if thumb and thumb.startswith('//'): thumb = 'https:' + thumb
            if not thumb: thumb = "https://picsum.photos/320/180"

            date_elem = item.find('span', class_='date') or item.find('div', class_='date')
            upload_text = date_elem.get_text(strip=True) if date_elem else ""
            
            videos.append({
                "title": title.strip(),
                "url": video_url,
                "thumbnail": thumb,
                "upload_text": upload_text,
                "source": "desihub"
            })
        except Exception as e:
            logger.debug(f"Error parsing DesiHub item: {e}")
            continue
    return videos

def parse_desitales2(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    videos = []
    items = soup.find_all('div', class_='video-item')
    if not items:
        items = soup.find_all('article')

    for item in items:
        try:
            link_tag = item.find('a', href=True)
            if not link_tag: continue
            
            video_url = link_tag['href']
            if not video_url.startswith('http'): video_url = base_url.rstrip('/') + '/' + video_url.lstrip('/')

            title = link_tag.get('title', '')
            if not title:
                header = item.find(['h2', 'h3'])
                if header: title = header.get_text(strip=True)

            img_tag = item.find('img')
            thumb = img_tag.get('data-src') if img_tag and img_tag.has_attr('data-src') else None
            if not thumb and img_tag: thumb = img_tag['src']
            if thumb and thumb.startswith('//'): thumb = 'https:' + thumb
            if not thumb: thumb = "https://picsum.photos/320/180"

            date_elem = item.find('span', class_='time') or item.find('div', class_='meta-info')
            upload_text = date_elem.get_text(strip=True) if date_elem else ""

            videos.append({
                "title": title.strip() or "Video",
                "url": video_url,
                "thumbnail": thumb,
                "upload_text": upload_text,
                "source": "desitales2"
            })
        except Exception as e:
            logger.debug(f"Error parsing DesiTales2 item: {e}")
            continue
    return videos

def parse_leakvids(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    videos = []
    # LeakVids usually uses <div class="item"> for video cards
    items = soup.find_all('div', class_='item')
    if not items:
        items = soup.find_all('div', class_='video-thumb')

    for item in items:
        try:
            link_tag = item.find('a', href=True)
            if not link_tag: continue

            video_url = link_tag['href']
            if not video_url.startswith('http'): video_url = base_url.rstrip('/') + '/' + video_url.lstrip('/')

            title = link_tag.get('title', '')
            if not title:
                title = link_tag.img.get('alt', '') if link_tag.find('img') else "Video"

            img_tag = link_tag.find('img')
            thumb = img_tag.get('data-original') if img_tag and img_tag.has_attr('data-original') else None
            if not thumb and img_tag: thumb = img_tag['src']
            if thumb and thumb.startswith('//'): thumb = 'https:' + thumb
            if not thumb: thumb = "https://picsum.photos/320/180"

            date_elem = item.find('span', class_='date')
            upload_text = date_elem.get_text(strip=True) if date_elem else ""

            videos.append({
                "title": title.strip(),
                "url": video_url,
                "thumbnail": thumb,
                "upload_text": upload_text,
                "source": "leakvids"
            })
        except Exception as e:
            logger.debug(f"Error parsing LeakVids item: {e}")
            continue
    return videos

# ==========================================
#           BOT LOGIC
# ==========================================
def is_within_24_hours(upload_text):
    if not upload_text: return True
    upload_text = upload_text.lower()
    if "hour" in upload_text:
        try:
            hours = int(upload_text.split()[0])
            return hours <= 24
        except: return True
    elif "day" in upload_text:
        try:
            days = float(upload_text.split()[0])
            return days <= 1.0
        except: return True
    elif "min" in upload_text or "just now" in upload_text:
        return True
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_USER_ID:
        await update.message.reply_text("Access Denied.")
        return
    await update.message.reply_text("🤖 Bot is monitoring your sites.")

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_USER_ID: return

    await update.message.reply_text("🔍 Checking websites...")
    seen = load_seen_videos()
    new_videos = []
    
    for url in WEBSITE_URLS:
        raw_videos = parse_videos(url)
        for vid in raw_videos:
            if vid['url'] in seen: continue
            
            if is_within_24_hours(vid['upload_text']):
                new_videos.append(vid)
                save_seen_video(vid['url']) 
            else:
                save_seen_video(vid['url'])

    if not new_videos:
        await update.message.reply_text("✅ No new videos (< 24h).")
    else:
        for vid in new_videos:
            await send_video_post(context, vid)

async def send_video_post(context, vid):
    keyboard = [
        [
            InlineKeyboardButton("Open 😺", url=vid['url']),
            InlineKeyboardButton("Skip ❌", callback_data=f"skip_{vid['url']}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Safe Caption Generation
    safe_title = escape_markdown(vid['title'])
    safe_source = escape_markdown(vid['source'])
    safe_time = escape_markdown(vid['upload_text'])
    
    # Using MarkdownV2 format
    caption = f"🎬 *{safe_title}*\n🔗 Source: {safe_source}\n⏱ {safe_time}"

    try:
        await context.bot.send_photo(
            chat_id=OWNER_USER_ID,
            photo=vid['thumbnail'],
            caption=caption,
            parse_mode='MarkdownV2',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Send error: {e}")
        # Fallback to plain text if Markdown fails or photo fails
        await context.bot.send_message(
            chat_id=OWNER_USER_ID,
            text=vid['title'] + "\n" + vid['url'],
            reply_markup=reply_markup
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_USER_ID: return

    if query.data.startswith("skip_"):
        # 1. Delete the message from Telegram
        try:
            await query.message.delete()
        except Exception:
            pass # Ignore if already deleted or error
            
        # 2. Permanently mark as skipped by saving to file
        try:
            # Extract URL from callback data (skip_https://...)
            url = query.data.replace("skip_", "")
            save_seen_video(url)
            logger.info(f"Permanently skipped: {url}")
        except Exception as e:
            logger.error(f"Error saving skip: {e}")

async def background_loop(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running background check...")
    seen = load_seen_videos()
    for url in WEBSITE_URLS:
        raw_videos = parse_videos(url)
        for vid in raw_videos:
            if vid['url'] not in seen:
                if is_within_24_hours(vid['upload_text']):
                    await send_video_post(context, vid)
                    save_seen_video(vid['url'])
                else:
                    save_seen_video(vid['url'])

# ==========================================
#           FLASK & WEBHOOK
# ==========================================
@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

@app.route('/')
def home():
    return "Bot Active V2.0"

if __name__ == '__main__':
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", manual_check))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Background Job
    job_queue = application.job_queue
    job_queue.run_repeating(background_loop, interval=CHECK_INTERVAL_MINUTES * 60, first=10)
    
        # Webhook
    port = int(os.environ.get('PORT', 8080))
    url = os.environ.get('RENDER_EXTERNAL_URL', 'https://example.com')
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{url}/{BOT_TOKEN}"
    )
    )
