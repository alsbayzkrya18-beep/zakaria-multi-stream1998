import telebot
import threading
from flask import Flask
import subprocess
import os
import logging
import re
import time

# إعداد التسجيل (Logging)
logging.basicConfig(level=logging.INFO, format=\'%(asctime)s - %(levelname)s - %(message)s\')

# الحصول على التوكن من متغيرات البيئة
API_TOKEN = os.environ.get(\'TELEGRAM_BOT_TOKEN\')
if not API_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN is missing from environment variables!")
    exit(1)

bot = telebot.TeleBot(API_TOKEN)

# تخزين الجلسات والبث النشط
user_sessions = {}
active_streams = {}

# دالة لتشغيل البوت في Thread منفصل
def run_bot_polling():
    logging.info("Bot polling thread started...")
    while True:
        try:
            bot.infinity_polling(none_stop=True, timeout=60)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5) # انتظر قليلاً قبل إعادة المحاولة

@bot.message_handler(commands=[\'start\', \'stream\'])
def start_command(message):
    chat_id = message.chat.id
    welcome_text = (
        "🎬 **مرحباً بك في محرك زكريا برو المطور (النسخة النهائية)!** 🚀\\n\\n"
        "أرسل رابط الفيديو أو البث المباشر الآن:"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")
    user_sessions[chat_id] = {\'step\': \'WAITING_URL\'}

@bot.message_handler(commands=[\'stop\'])
def stop_stream(message):
    chat_id = message.chat.id
    if chat_id in active_streams:
        process = active_streams[chat_id][\'process\']
        process.terminate()
        process.wait() # انتظر حتى ينتهي العملية
        del active_streams[chat_id]
        bot.reply_to(message, "🛑 تم إيقاف البث بنجاح.")
    else:
        bot.reply_to(message, "❌ لا يوجد بث نشط حالياً.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id not in user_sessions:
        bot.reply_to(message, "الرجاء استخدام /start لبدء جلسة جديدة.")
        return

    step = user_sessions[chat_id][\'step\']

    # 1. استلام الرابط وتنظيفه
    if step == \'WAITING_URL\':
        url_match = re.search(r\'https?://\\S+\', text)
        if url_match:
            clean_url = url_match.group(0)
            user_sessions[chat_id][\'url\'] = clean_url
            bot.reply_to(message, f"✅ تم حفظ الرابط:\\n`{clean_url}`\\n\\n📍 أرسل الآن رابط الـ RTMP (عنوان السيرفر + المفتاح):", parse_mode="Markdown")
            user_sessions[chat_id][\'step\'] = \'WAITING_DEST\'
        else:
            bot.reply_to(message, "❌ يرجى إرسال رابط صالح.")

    # 2. بدء البث
    elif step == \'WAITING_DEST\':
        destination = text
        source_url = user_sessions[chat_id][\'url\']
        
        if chat_id in active_streams:
            bot.reply_to(message, "⚠️ هناك بث يعمل بالفعل. استخدم /stop أولاً.")
            return

        bot.reply_to(message, "🚀 جاري فك التشفير وبدء البث... انتظر قليلاً...")

        try:
            direct_url = source_url
            # إذا لم يكن الرابط مباشراً، حاول استخراجه باستخدام yt-dlp
            if not any(ext in source_url.lower() for ext in [\'.m3u8\', \'.mp4\', \'.mkv\', \'.ts\', \'.webm\']):
                logging.info(f"Attempting to extract direct URL for: {source_url}")
                yt_dlp_cmd = [
                    "yt-dlp",
                    "--no-check-certificate",
                    "--no-playlist",
                    "--ignore-errors",
                    "--no-warnings",
                    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                    "--extractor-args", "youtube:player_client=ios,android,web",
                    "--geo-bypass",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "-g", source_url
                ]
                
                result = subprocess.run(yt_dlp_cmd, capture_output=True, text=True, encoding=\'utf-8\', timeout=60)
                if result.returncode != 0:
                    error_msg = f"❌ فشل فك التشفير:\\n`{result.stderr[-500:]}`"
                    bot.send_message(chat_id, error_msg, parse_mode="Markdown")
                    logging.error(f"yt-dlp failed: {result.stderr}")
                    return

                direct_urls = [line.strip() for line in result.stdout.split(\'\\n\') if line.strip().startswith(\'http\')]
                if not direct_urls:
                    bot.send_message(chat_id, "❌ لم يتم العثور على رابط مباشر بواسطة yt-dlp.")
                    logging.error("yt-dlp returned no direct URLs.")
                    return
                direct_url = direct_urls[-1]
                logging.info(f"Direct URL extracted: {direct_url}")

            # أمر FFmpeg المطور مع إعدادات توافق قصوى لفيسبوك ويوتيوب
            ffmpeg_cmd = [
                "ffmpeg", "-re", "-i", direct_url,
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "2000k", "-maxrate", "2000k", "-bufsize", "4000k",
                "-pix_fmt", "yuv420p", "-g", "60", "-r", "30",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-f", "flv", "-flvflags", "no_duration_filesize",
                "-rtmp_buffer", "2000", "-rtmp_live", "live",
                "-tls_verify", "0", # تجاوز مشاكل شهادات RTMPS (قد لا يكون مدعوماً في كل إصدارات ffmpeg)
                destination
            ]
            logging.info(f"FFmpeg command: {\' \'.join(ffmpeg_cmd)}")

            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # مراقبة البث لمدة 10 ثوانٍ للتأكد من بدء الاتصال
            time.sleep(10)
            if process.poll() is not None: # إذا توقفت العملية مبكراً
                _, stderr = process.communicate()
                error_msg = f"❌ فشل الاتصال بالمنصة أو بدء البث:\\n`{stderr[-500:]}`"
                bot.send_message(chat_id, error_msg, parse_mode="Markdown")
                logging.error(f"FFmpeg failed to start: {stderr}")
                return

            active_streams[chat_id] = {\'process\': process}
            
            bot.send_message(chat_id, "✅ **تم بدء محرك البث!**\\n\\n📊 **تقرير الحالة الأولي:**\\nجاري إرسال البيانات... انتظر 20 ثانية لتظهر الصورة على منصة البث.\\n\\n🎯 أوقف البث بـ /stop")
            logging.info(f"Stream started for chat_id {chat_id} to {destination}")

        except subprocess.TimeoutExpired:
            bot.send_message(chat_id, "❌ استغرق فك التشفير وقتاً طويلاً جداً. يرجى المحاولة برابط آخر.")
            logging.error(f"yt-dlp timeout for {source_url}")
        except Exception as e:
            bot.send_message(chat_id, f"❌ خطأ غير متوقع أثناء معالجة البث: {str(e)}")
            logging.error(f"Unexpected error: {e}", exc_info=True)
        
        finally:
            if chat_id in user_sessions: # تأكد من حذف الجلسة فقط إذا كانت موجودة
                del user_sessions[chat_id]


# تشغيل Flask في العملية الرئيسية وتشغيل البوت في Thread
if __name__ == "__main__":
    # بدء البوت في Thread منفصل
    bot_thread = threading.Thread(target=run_bot_polling)
    bot_thread.daemon = True
    bot_thread.start()

    # تشغيل Flask في العملية الرئيسية
    app = Flask(__name__)

    @app.route(\'/\')
    def home():
        return "Bot is alive!"

    port = int(os.environ.get(\'PORT\', 8080))
    logging.info(f"Flask server running on port {port}")
    app.run(host=\'0.0.0.0\', port=port)
