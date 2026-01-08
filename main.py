import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
import logging

# ==========================================
#           CONFIGURATION
# ==========================================
BOT_TOKEN = os.environ.get("TOKEN")
OWNER_USER_ID = int(os.environ.get("OWNER_USER_ID", "0"))

# WEBSITES TO CHECK
WEBSITE_URLS = [
    "https://desihub.org/",
    "https://www.desitales2.com/videos/latest-updates/",
    "https://leakvids.com/tags/leaked/"
]

CHECK_INTERVAL_MINUTES = 5

# ==========================================
#           SETUP
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SEEN_FILE = "seen_videos.txt"

def load_seen_videos():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_seen_video(url):
    with open(SEEN_FILE, "a") as f:
        f.write(url + "\n")

# ==========================================
#           SMART PARSING LOGIC
# ==========================================
def fetch_html(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

def parse_videos(url):
    html = fetch_html(url)
    if not html: return []

    soup = BeautifulSoup(html, 'html.parser')
    videos = []
    
    # SMART PARSING LOGIC:
    # We look for links that behave like videos.
    # We assume a video link has a thumbnail image nearby.
    
    # Keywords commonly found in video URLs
    video_keywords = ['/video/', '/videos/', '/watch/', '/view/', '/post/', '/clip/', '/v/']
    
    # Find all links on the page
    all_links = soup.find_all('a', href=True)
    
    for link in all_links:
        try:
            href = link['href']
            
            # Check if URL looks like a video page
            is_video = any(keyword in href.lower() for keyword in video_keywords)
            
            # If it doesn't contain obvious keywords, check if it's a main content link
            # (Some sites use simple slugs like /title-name)
            if not is_video:
                # Skip navigation/login links
                skip_keywords = ['/login', '/register', '/category', '/tag', '/user', '/search', '/page', '#', 'javascript', 'mailto']
                if any(skip in href.lower() for skip in skip_keywords):
                    continue
                
                # If it's not a skip-link, check if it has an image inside
                if link.find('img'):
                    is_video = True
            
            if is_video:
                # Ensure URL is absolute
                if not href.startswith('http'):
                    # Construct base URL
                    if url.startswith('http'):
                        parts = url.split('/')
                        base_url = parts[0] + '//' + parts[2]
                        href = base_url + href
                
                # Get Title
                title = link.get('title', '')
                if not title:
                    # Try to get text inside the link
                    title = link.get_text(strip=True)
                if not title:
                    # Try alt text of image
                    img = link.find('img')
                    if img:
                        title = img.get('alt', 'No Title')
                
                # Get Thumbnail
                img = link.find('img')
                thumb = None
                if img:
                    thumb = img.get('data-src') or img.get('data-original') or img.get('src')
                
                if not thumb:
                    continue # No image = likely not a video card
                
                # Clean thumbnail URL
                if not thumb.startswith('http'):
                    if thumb.startswith('//'):
                        thumb = 'https:' + thumb
                    else:
                        parts = url.split('/')
                        base_url = parts[0] + '//' + parts[2]
                        thumb = base_url + thumb

                videos.append({
                    "title": title.strip(),
                    "url": href,
                    "thumbnail": thumb
                })
                
        except Exception as e:
            continue

    # Remove Duplicates (Simple check by URL)
    unique_videos = []
    seen_urls = set()
    for v in videos:
        if v['url'] not in seen_urls:
            unique_videos.append(v)
            seen_urls.add(v['url'])
            
    return unique_videos

# ==========================================
#           BOT HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_USER_ID:
        await update.message.reply_text("Access Denied.")
        return
    await update.message.reply_text("🤖 Render Bot is Active.\nMonitoring websites...")

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_USER_ID: return
    await update.message.reply_text("🔍 Checking websites...")
    
    seen = load_seen_videos()
    count = 0
    for url in WEBSITE_URLS:
        raw = parse_videos(url)
        for vid in raw:
            if vid['url'] in seen: continue
            await send_post(context, vid)
            save_seen_video(vid['url'])
            count += 1
    
    if count == 0:
        await update.message.reply_text("✅ No new videos found.")

async def send_post(context, vid):
    # Simple "Open" button only
    keyboard = [[InlineKeyboardButton("Open 🔗", url=vid['url'])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Safe Title
    safe_title = vid['title'].replace("*", "").replace("_", "").replace("[", "").replace("]", "")
    
    try:
        await context.bot.send_photo(
            chat_id=OWNER_USER_ID,
            photo=vid['thumbnail'],
            caption=f"🎬 {safe_title}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Failed to send photo: {e}")
        await context.bot.send_message(
            chat_id=OWNER_USER_ID,
            text=f"{safe_title}\n{vid['url']}",
            reply_markup=reply_markup
        )

async def background_loop(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running background check...")
    seen = load_seen_videos()
    for url in WEBSITE_URLS:
        raw = parse_videos(url)
        for vid in raw:
            if vid['url'] not in seen:
                await send_post(context, vid)
                save_seen_video(vid['url'])

# ==========================================
#           WEBHOOK SERVER (For Render)
# ==========================================
from flask import Flask, request
app = Flask(__name__)

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

@app.route('/')
def home():
    return "Render Bot Live"

if __name__ == '__main__':
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", manual_check))
    
    # Background Job
    job_queue = application.job_queue
    job_queue.run_repeating(background_loop, interval=CHECK_INTERVAL_MINUTES * 60, first=10)
    
    # Render Webhook Setup
    port = int(os.environ.get('PORT', 8080))
    # Render automatically sets RENDER_EXTERNAL_URL
    url = os.environ.get('RENDER_EXTERNAL_URL') 
    
    if not url:
        logger.error("RENDER_EXTERNAL_URL not found. Webhook may fail.")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{url}/{BOT_TOKEN}"
                        )
