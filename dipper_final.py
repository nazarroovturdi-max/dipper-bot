import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from groq import Groq
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ================================
# 🔑 ОБНОВЛЕННЫЕ КЛЮЧИ
# ================================
TELEGRAM_TOKEN = "8816461258:AAFyybkTSZQzugzQl-QR9jFuq1ukcPN6MEI"
GROQ_API_KEY = "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"
# ================================

REMINDERS_FILE = "reminders.json"
TIMEZONE = pytz.timezone("Asia/Tashkent")

SYSTEM_PROMPT = "Ты ИИ-ассистент Диппер. Отвечай развернуто, понятно, грамотно, до конца доноси свои мысли."

groq_client = Groq(api_key=GROQ_API_KEY)
scheduler = BackgroundScheduler(timezone=TIMEZONE)

user_histories = {}
telegram_app = None

def load_reminders():
    if Path(REMINDERS_FILE).exists():
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return []
    return []

def save_reminders(reminders):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)

def send_reminder_sync(chat_id, text):
    import asyncio
    if telegram_app is None: return
    msg = f"⏰ Напоминание: {text}"
    asyncio.run_coroutine_threadsafe(
        telegram_app.bot.send_message(chat_id=chat_id, text=msg),
        telegram_app.loop if hasattr(telegram_app, 'loop') else asyncio.get_event_loop()
    )

def parse_reminder_text(text):
    time_match = re.search(r'(\d{1,2}):(\d{2})', text)
    if not time_match:
        return None
    
    hours, minutes = int(time_match.group(1)), int(time_match.group(2))
    now = datetime.now(TIMEZONE)
    target_dt = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    
    if target_dt < now:
        target_dt += timedelta(days=1)
        
    # ИСПРАВЛЕНО: Безопасное удаление только ключевых слов, буквы в тексте больше не срезаются
    clean_text = text
    clean_text = re.sub(r'(напомни мне|напомни|поставь напоминание|напоминание|будильник)', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(сегодня|завтра|в|по ташкентскому времени|времени)\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b\d{1,2}:\d{2}\b', '', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    return {"datetime": target_dt, "text": clean_text if clean_text else "Будильник!"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await update.message.reply_text("Привет! Я Диппер. Напиши мне время и задачу (например: 18:30 выпить воды), и я напомню!")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await update.message.reply_text("История очищена! 🌿")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r["chat_id"] == update.effective_chat.id]
    if not user_reminders:
        await update.message.reply_text("У тебя пока нет активных напоминаний.")
        return
    msg = "📋 Твои активные напоминания:\n"
    for idx, r in enumerate(user_reminders, 1):
        msg += f"{idx}. {r['datetime']} — {r['text']}\n"
    await update.message.reply_text(msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if any(word in user_text.lower() for word in ["напомни", "напоминание", "будильник"]):
        parsed = parse_reminder_text(user_text)
        if parsed:
            dt = parsed["datetime"]
            text = parsed["text"]
            
            dt_before = dt - timedelta(minutes=10)
            now = datetime.now(TIMEZONE)
            
            if dt_before > now:
                scheduler.add_job(send_reminder_sync, trigger=DateTrigger(run_date=dt_before), args=[chat_id, text])
            if dt > now:
                scheduler.add_job(send_reminder_sync, trigger=DateTrigger(run_date=dt), args=[chat_id, text])
                
            reminders = load_reminders()
            reminders.append({"chat_id": chat_id, "datetime": dt.strftime("%Y-%m-%d %H:%M"), "text": text})
            save_reminders(reminders)
            
            await update.message.reply_text(f"⏰ Понял! Создал напоминание: \"{text}\" на {dt.strftime('%H:%M')}.")
            return

    user_histories[user_id].append({"role": "user", "content": user_text})
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=user_histories[user_id],
            max_tokens=1024,
        )
        reply = response.choices.message.content.strip()
        user_histories[user_id].append({"role": "assistant", "content": reply})
        
        if len(user_histories[user_id]) > 11:
            user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id][-10:]

        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"⚙️ Ошибка: {str(e)[:100]}")

def main():
    global telegram_app
    scheduler.start()
    telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).connect_timeout(30.0).read_timeout(30.0).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("clear", clear))
    telegram_app.add_handler(CommandHandler("reminders", list_reminders))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Умный Диппер онлайн!")
    telegram_app.run_polling()

if __name__ == "__main__":
    main()
