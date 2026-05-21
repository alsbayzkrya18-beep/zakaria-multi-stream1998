import telebot
import threading
from flask import Flask
import subprocess
import os
import logging
import re
import time

# إعداد التسجيل (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# الحصول على التوكن من متغيرات البيئة
API_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not API_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN is missing from environment variables!")
    exit(1)

bot = telebot.TeleBot(API_TOKEN)

# تخزين الجلسات والبث النشط
user_sessions = {}
active_streams = {}

# إصلاح دالة keep_alive لتعمل بشكل صحيح على منصة Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running clean! 🚀"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logging.info("Flask keep-alive server started successfully.")

@bot.message_handler(commands=['start', 'stream'])
def start_command(message):
    chat_id = message.chat.id
    welcome_text = (
        "🎬 **مرحباً بك في محرك زكريا برو المطور (النسخة النهائية النظيفة)!** 🚀\n\n"
        "أرسل رابط الفيديو أو البث المباشر الآن:"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")
    user_sessions[chat_id] = {'step': 'WAITING_URL'}

@bot.message_handler(commands=['stop'])
def stop_stream(message):
    chat_id = message.chat.id
    if chat_id in active_streams:
        process = active_streams[chat_id]['process']
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill() # قتل العملية بالقوة إذا لم تستجب للتوقف العادي
        del active_streams[chat_id]
        bot.reply_to(message, "🛑 تم إيقاف البث بنجاح وتفريغ الذاكرة.")
    else:
        bot.reply_to(message, "❌ لا يوجد بث نشط حالياً.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id not in user_sessions:
        bot.reply_to(message, "الرجاء استخدام /start لبدء جلسة جديدة.")
        return

    step = user_sessions[chat_id]['step']

    # 1. استلام الرابط وتنظيفه
    if step == 'WAITING_URL':
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            clean_url = url_match.group(0)
            user_sessions[chat_id]['url'] = clean_url
            bot.reply_to(message, f"✅ تم حفظ الرابط:\n`{clean_url}`\n\n📍 أرسل الآن رابط الـ RTMP الكامل (عنوان السيرفر + المفتاح الخاص بالفيسبوك):", parse_mode="Markdown")
            user_sessions[chat_id]['step'] = 'WAITING_DEST'
        else:
            bot.reply_to(message, "❌ يرجى إرسال رابط صالح.")

    # 2. بدء البث المباشر
    elif step == 'WAITING_DEST':
        destination = text
        source_url = user_sessions[chat_id]['url']
        
        if chat_id in active_streams:
            bot.reply_to(message, "⚠️ هناك بث يعمل بالفعل. استخدم /stop أولاً.")
            return

        bot.reply_to(message, "🚀 جاري تشغيل المحرك وفك التشفير... انتظر قليلاً...")

        try:
            direct_url = source_url
            # فحص إذا كان الرابط يحتاج لـ yt-dlp
            if not any(ext in source_url.lower() for ext in ['.m3u8', '.mp4', '.mkv', '.ts', '.webm']):
                logging.info(f"Attempting to extract direct URL for: {source_url}")
                yt_dlp_cmd = [
                    "yt-dlp",
                    "--no-check-certificate",
                    "--no-playlist",
                    "--ignore-errors",
                    "--no-warnings",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "-g", source_url
                ]
                
                result = subprocess.run(yt_dlp_cmd, capture_output=True, text=True, encoding='utf-8', timeout=60)
                if result.returncode != 0:
                    error_msg = f"❌ فشل فك التشفير عبر yt-dlp:\n`{result.stderr[-200:]}`"
                    bot.send_message(chat_id, error_msg, parse_mode="Markdown")
                    return

                direct_urls = [line.strip() for line in result.stdout.split('\n') if line.strip().startswith('http')]
                if not direct_urls:
                    bot.send_message(chat_id, "❌ لم يتم العثور على رابط مباشر.")
                    return
                direct_url = direct_urls[-1]

            # أمر FFmpeg الاحترافي المطور الخاص بك للتوافق مع فيسبوك
            ffmpeg_cmd = [
                "ffmpeg", "-re", "-i", direct_url,
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "2000k", "-maxrate", "2000k", "-bufsize", "4000k",
                "-pix_fmt", "yuv420p", "-g", "60", "-r", "30",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-f", "flv", "-flvflags", "no_duration_filesize",
                "-rtmp_buffer", "2000", "-rtmp_live", "live",
                destination
            ]

            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # مراقبة البث للتأكد من انطلاقه بنجاح
            time.sleep(8)
            if process.poll() is not None:
                _, stderr = process.communicate()
                error_msg = f"❌ فشل الاتصال بالمنصة المستهدفة:\n`{stderr[-200:]}`"
                bot.send_message(chat_id, error_msg, parse_mode="Markdown")
                return

            active_streams[chat_id] = {'process': process}
            bot.send_message(chat_id, "🎯 **البث انطلق ويعمل الآن بنجاح!**\n\n📊 تفقد صفحة البث في فيسبوك الآن.\n\n🛑 لإيقاف البث في أي وقت أرسل: /stop")

        except subprocess.TimeoutExpired:
            bot.send_message(chat_id, "❌ استغرق فك التشفير وقتاً طويلاً جداً.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ خطأ غير متوقع: {str(e)}")
        finally:
            if chat_id in user_sessions:
                del user_sessions[chat_id]

if __name__ == "__main__":
    keep_alive() # تشغيل سيرفر ويب Flask بنجاح
    logging.info("Bot is starting polling...")
    
    # حلقة حماية ذكية لتخطي خطأ الـ Conflict 409 القديم نهائياً عند بدء التشغيل
    while True:
        try:
            bot.infinity_polling(none_stop=True, timeout=60, skip_pending=True)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)
