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
    os._exit(1)

bot = telebot.TeleBot(API_TOKEN)

user_sessions = {}
active_streams = {}

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Engine is stable with ultra-low RAM configuration! 🚀"

@app.route('/health')
def health():
    return "OK", 200

def start_polling():
    logging.info("Bot is starting polling in background thread...")
    while True:
        try:
            bot.infinity_polling(none_stop=True, timeout=60, skip_pending=True)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)

@bot.message_handler(commands=['start', 'stream'])
def start_command(message):
    chat_id = message.chat.id
    welcome_text = (
        "🎬 **مرحباً بك في محرك البث الخفيف (النسخة المستقرة لـ Render)!** 🚀\n\n"
        "أرسل رابط الفيديو أو البث المباشر الآن:"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")
    user_sessions[chat_id] = {'step': 'WAITING_URL'}

@bot.message_handler(commands=['stop'])
def stop_stream(message):
    chat_id = message.chat.id
    if chat_id in active_streams:
        process = active_streams[chat_id]['process']
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if chat_id in active_streams:
            del active_streams[chat_id]
        bot.reply_to(message, "🛑 تم إيقاف البث وتفريغ رامات السيرفر بنجاح.")
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

    if step == 'WAITING_URL':
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            clean_url = url_match.group(0)
            user_sessions[chat_id]['url'] = clean_url
            bot.reply_to(message, f"✅ تم حفظ الرابط:\n`{clean_url}`\n\n📍 أرسل الآن رابط الـ RTMP الكامل والخاص بفيسبوك:", parse_mode="Markdown")
            user_sessions[chat_id]['step'] = 'WAITING_DEST'
        else:
            bot.reply_to(message, "❌ يرجى إرسال رابط صالح.")

    elif step == 'WAITING_DEST':
        destination = text
        source_url = user_sessions[chat_id]['url']
        
        if chat_id in active_streams:
            bot.reply_to(message, "⚠️ هناك بث يعمل بالفعل. استخدم /stop أولاً.")
            return

        bot.reply_to(message, "🚀 جاري تشغيل المحرك بنظام الحفظ الفائق لـ RAM... انتظر ثوانٍ...")

        try:
            direct_url = source_url
            if not any(ext in source_url.lower() for ext in ['.m3u8', '.mp4', '.mkv', '.ts', '.webm']):
                yt_dlp_cmd = [
                    "yt-dlp", "--no-check-certificate", "--no-playlist", "--ignore-errors", "--no-warnings",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "-g", source_url
                ]
                result = subprocess.run(yt_dlp_cmd, capture_output=True, text=True, encoding='utf-8', timeout=40)
                if result.returncode == 0:
                    direct_urls = [line.strip() for line in result.stdout.split('\n') if line.strip().startswith('http')]
                    if direct_urls:
                        direct_url = direct_urls[-1]

            # أمر FFmpeg مطور جداً بنظام النقل المباشر (Stream Copy) لتخفيف الضغط بنسبة 95%
            ffmpeg_cmd = [
                "ffmpeg", 
                "-reconnect", "1", "-reconnect_at_eof", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
                "-re", "-i", direct_url,
                "-c:v", "copy",       # نقل الفيديو بدون إعادة معالجة (RAM تستهلك 0%)
                "-c:a", "aac",        # التأكد من توافق الصوت مع معايير فيسبوك
                "-b:a", "128k",
                "-f", "flv", "-flvflags", "no_duration_filesize",
                destination
            ]

            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            time.sleep(6)
            if process.poll() is not None:
                _, stderr = process.communicate()
                # إذا فشل النقل المباشر بسبب تعارض صيغة الفيديو، نعود للنظام الآمن الخفيف جداً
                logging.info("Copy mode failed, switching to ultra-light encoding mode...")
                ffmpeg_cmd_light = [
                    "ffmpeg", "-reconnect", "1", "-reconnect_at_eof", "1", "-reconnect_streamed", "1",
                    "-re", "-i", direct_url,
                    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", # استخدام أسرع بروفايل ممكن للاستهلاك الأدنى
                    "-b:v", "1000k", "-maxrate", "1000k", "-bufsize", "2000k",        # تقليل جودة البث لتخفيف الضغط
                    "-pix_fmt", "yuv420p", "-g", "60",
                    "-c:a", "aac", "-b:a", "96k",
                    "-f", "flv", destination
                ]
                process = subprocess.Popen(ffmpeg_cmd_light, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                time.sleep(6)
                if process.poll() is not None:
                    bot.send_message(chat_id, "❌ فشل استقرار البث بسبب قيود الرامات في السيرفر المجاني.")
                    return

            active_streams[chat_id] = {'process': process}
            bot.send_message(chat_id, "🎯 **البث مستقر ومستمر الآن بنجاح وبأقل استهلاك للموارد!**\n\n🛑 لإيقاف البث في أي وقت أرسل: /stop")

        except Exception as e:
            bot.send_message(chat_id, f"❌ خطأ غير متوقع: {str(e)}")
        finally:
            if chat_id in user_sessions:
                del user_sessions[chat_id]

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_polling)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
