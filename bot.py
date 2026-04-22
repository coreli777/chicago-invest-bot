import os
import logging
import httpx
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import anthropic

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8080))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_SEARCH_ID = os.environ.get("GOOGLE_SEARCH_ID", "")
CHAT_ID = os.environ.get("CHAT_ID", "7037686908")

# ✅ HTTP сервер в главном потоке — никогда не останавливается
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass

SYSTEM_PROMPT = """Ты профессиональный риелтор в Чикаго. Критерии: до $700K, multifamily, аренда, отдельные счётчики.
Районы: Pilsen, Logan Square, Avondale (отличные), Wicker Park, Irving Park (хорошие), Englewood (избегать).
Анализируй: цена/unit, Cap Rate, GRM, аренда/мес. Отвечай на языке пользователя."""

conversations = {}

async def fetch_url(url):
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            return r.text[:5000]
    except Exception as e:
        return f"Ошибка: {e}"

async def run_bot():
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters, ContextTypes

    ai_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            text = update.message.text
            if user_id not in conversations:
                conversations[user_id] = []
            urls = [w for w in text.split() if w.startswith("http")]
            if urls:
                await update.message.reply_text("🔍 Анализирую...")
                pages = ""
                for i, url in enumerate(urls[:3], 1):
                    pages += f"\n=== ОБЪЕКТ {i} ===\n{await fetch_url(url)}"
                text = f"Проанализируй:\n{pages}"
            conversations[user_id].append({"role": "user", "content": text})
            if len(conversations[user_id]) > 20:
                conversations[user_id] = conversations[user_id][-20:]
            await update.message.chat.send_action("typing")
            response = ai_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=conversations[user_id]
            )
            reply = response.content[0].text
            conversations[user_id].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)
        except Exception as e:
            log.error(f"Message error: {e}")

    async def auto_search(context):
        try:
            found = []
            async with httpx.AsyncClient(timeout=15) as c:
                for q in ["site:zillow.com multifamily Chicago for sale under 700000",
                          "site:redfin.com multifamily Chicago IL for sale"]:
                    r = await c.get("https://www.googleapis.com/customsearch/v1",
                        params={"key": GOOGLE_API_KEY, "cx": GOOGLE_SEARCH_ID, "q": q, "num": 3})
                    found.extend(r.json().get("items", []))
            seen = set()
            unique = [i for i in found if i.get("link") not in seen and not seen.add(i.get("link"))]
            if unique:
                msg = "🏠 <b>НОВЫЕ ОБЪЕКТЫ В ЧИКАГО!</b>\n\n"
                for i, item in enumerate(unique[:5], 1):
                    msg += f"{i}. <b>{item.get('title','')[:60]}</b>\n{item.get('snippet','')[:100]}\n🔗 <a href='{item.get('link','')}'>Открыть</a>\n\n"
                await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            log.error(f"Search error: {e}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_search, interval=1800, first=60)
    log.info("🚀 Telegram bot started!")
    await app.run_polling()

def bot_thread():
    """Бот работает в отдельном потоке — если упадёт, HTTP сервер продолжает работать"""
    try:
        asyncio.run(run_bot())
    except Exception as e:
        log.error(f"Bot crashed: {e}")

if __name__ == "__main__":
    # ✅ Запускаем бота в отдельном потоке
    t = threading.Thread(target=bot_thread, daemon=True)
    t.start()
    log.info(f"✅ Bot thread started")

    # ✅ HTTP сервер в главном потоке — Cloud Run всегда получает ответ на порту 8080
    log.info(f"✅ HTTP server starting on port {PORT}")
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()  # ← главный поток никогда не завершается



