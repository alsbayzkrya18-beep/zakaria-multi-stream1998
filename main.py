import telebot
import threading
from flask import Flask
import subprocess
import os
import logging
import re
import time
import yt_dlp # Import yt_dlp library

# إعداد الـ Logging لمراقبة الأخطاء
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

API_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not API_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN is missing!")
    os._exit(1)

bot = telebot.TeleBot(API_TOKEN)
user_sessions = {}
active_streams = {}

app = Flask(__name__)

@app.route('/')
def home():
    return "Stream Engine is Running Smoothly! 🚀"

@app.route('/health')
def health():
    return "OK", 200

def start_polling():
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
        "🎬 **مرحباً بك في محرك البث فائق الاستقرار!** 🚀\n\n"
        "أرسل رابط الـ IPTV أو رابط الفيديو الآن:"
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
        del active_streams[chat_id]
        bot.reply_to(message, "🛑 تم إيقاف البث وتفريغ الذاكرة بنجاح.")
    else:
        bot.reply_to(message, "❌ لا يوجد بث نشط حالياً.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id not in user_sessions:
        return

    step = user_sessions[chat_id]['step']

    if step == 'WAITING_URL':
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            clean_url = url_match.group(0)
            user_sessions[chat_id]['url'] = clean_url
            bot.reply_to(message, f"✅ تم حفظ الرابط بنجاح.\n\n📍 أرسل الآن رابط الـ **RTMP** الكامل الخاص بفيسبوك:", parse_mode="Markdown")
            user_sessions[chat_id]['step'] = 'WAITING_DEST'
        else:
            bot.reply_to(message, "❌ يرجى إرسال رابط صحيح يبدأ بـ http أو https.")

    elif step == 'WAITING_DEST':
        destination = text
        source_url = user_sessions[chat_id]['url']
        
        if chat_id in active_streams:
            bot.reply_to(message, "⚠️ هناك بث يعمل بالفعل. استخدم /stop أولاً.")
            return

        bot.reply_to(message, "⏳ جاري تهيئة الاتصال المباشر وتخفيف الضغط على السيرفر...")

        try:
            direct_url = source_url
            # التحقق مما إذا كان الرابط يحتاج استخراج عبر yt-dlp
            if not any(ext in source_url.lower() for ext in ['.m3u8', '.mp4', '.mkv', '.ts']):
                ydl_opts = {'quiet': True, 'simulate': True, 'force_generic_extractor': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(source_url, download=False)
                    if 'url' in info:
                        direct_url = info['url']
                    elif 'entries' in info:
                        # For playlists or multiple entries, take the first one
                        direct_url = info['entries'][0]['url']

            # أمر FFmpeg بنظام الحفظ الفائق للطاقة والذاكرة (Stream Copy)
            ffmpeg_cmd = [
                "ffmpeg", 
                "-reconnect", "1", "-reconnect_at_eof", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
                "-re", "-i", direct_url,
                "-c:v", "copy",  # نقل الفيديو كما هو بدون إعادة معالجة لمنع الانهيار 
                "-c:a", "aac",   # إعادة ترميز الصوت فقط لضمان التوافق مع فيسبوك
                "-b:a", "128k",
                "-f", "flv", 
                destination
            ]

            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            active_streams[chat_id] = {'process': process}
            
            # انتظار ثوانٍ للتأكد من استقرار العملية
            time.sleep(5)
            if process.poll() is not None:
                # إذا فشل نظام الـ copy بسبب صيغة الرابط، يتم الانتقال تلقائياً للنظام الخفيف للغاية
                ffmpeg_cmd_light = [
                    "ffmpeg", "-re", "-i", direct_url,
                    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                    "-b:v", "800k", "-maxrate", "800k", "-bufsize", "1200k", 
                    "-c:a", "aac", "-b:a", "96k",
                    "-f", "flv", destination
                ]
                process = subprocess.Popen(ffmpeg_cmd_light, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                active_streams[chat_id] = {'process': process}

            bot.send_message(chat_id, "🚀 **البث انطلق الآن وهو مستقر تماماً وبأقل استهلاك للموارد!**\n\n🛑 لإيقاف البث أرسل: /stop")

        except Exception as e:
            bot.send_message(chat_id, f"❌ حدث خطأ أثناء تشغيل البث: {str(e)}")
        finally:
            if chat_id in user_sessions:
                del user_sessions[chat_id]

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_polling)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
