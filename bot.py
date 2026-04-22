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

SYSTEM_PROMPT = """Ты профессиональный риелтор и инвестиционный консультант по недвижимости в Чикаго.

КРИТЕРИИ ИНВЕСТОРА:
- Бюджет: до $700,000
- Тип: многоквартирные дома (multifamily)
- Цель: сдача в аренду
- Локация: Чикаго и пригороды
- Обязательно: отдельные счётчики на каждый юнит

РАЙОНЫ ЧИКАГО:
🟢 Отличные: Pilsen, Logan Square, Avondale (Cap Rate 5-7%)
🟡 Хорошие: Wicker Park, Bucktown, Irving Park (Cap Rate 3-6%)
🔴 Избегать: Englewood, Austin, Roseland

АНАЛИЗ ОБЪЕКТА (всегда считай):
- Цена за юнит
- Годовой доход (аренда × юниты × 12)
- GRM = Цена ÷ Годовой доход (хорошо < 8)
- Cap Rate = Чистый доход ÷ Цена × 100
- Cash Flow после ипотеки
- ✅/❌ Подходит критериям

Отвечай на языке пользователя. Будь конкретным и давай чёткие рекомендации."""

conversations = {}

async def fetch_url(url):
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        ) as c:
            r = await c.get(url)
            return r.text[:5000]
    except Exception as e:
        return f"Ошибка загрузки: {e}"

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
                await update.message.reply_text("🔍 Анализирую объект...")
                pages = ""
                for i, url in enumerate(urls[:3], 1):
                    content = await fetch_url(url)
                    pages += f"\n=== ОБЪЕКТ {i} ===\n{content}"
                text = f"Проанализируй эти объекты по моим критериям:\n{pages}"
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
            await update.message.reply_text("Ошибка, попробуйте снова.")

    async def auto_search(context):
        try:
            # ✅ Ищем на Redfin и Loopnet — они не блокируют ботов
            queries = [
                "site:redfin.com multifamily Chicago IL for sale under 700000",
                "site:loopnet.com multifamily apartment Chicago for sale",
                "site:crexi.com multifamily Chicago Illinois for sale",
                "site:realtor.com multi-family Chicago IL under 700000",
            ]
            found = []
            async with httpx.AsyncClient(timeout=15) as c:
                for q in queries:
                    try:
                        r = await c.get(
                            "https://www.googleapis.com/customsearch/v1",
                            params={
                                "key": GOOGLE_API_KEY,
                                "cx": GOOGLE_SEARCH_ID,
                                "q": q,
                                "num": 3
                            }
                        )
                        data = r.json()
                        found.extend(data.get("items", []))
                    except Exception as e:
                        log.error(f"Search error: {e}")

            seen = set()
            unique = []
            for item in found:
                link = item.get("link", "")
                if link not in seen:
                    seen.add(link)
                    unique.append(item)

            if unique:
                msg = "🏠 <b>НОВЫЕ ОБЪЕКТЫ В ЧИКАГО!</b>\n\n"
                for i, item in enumerate(unique[:5], 1):
                    title = item.get("title", "")[:60]
                    snippet = item.get("snippet", "")[:120]
                    link = item.get("link", "")
                    msg += f"{i}. <b>{title}</b>\n"
                    msg += f"   {snippet}\n"
                    msg += f"   🔗 <a href='{link}'>Открыть</a>\n\n"
                msg += "💡 Отправьте ссылку боту для детального анализа!"
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                log.info(f"✅ Sent {len(unique)} listings")
            else:
                log.info("⚠️ No listings found this round")
        except Exception as e:
            log.error(f"Auto search error: {e}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_search, interval=1800, first=60)
    log.info("🚀 Telegram bot started!")
    await app.run_polling()

def bot_thread():
    try:
        asyncio.run(run_bot())
    except Exception as e:
        log.error(f"Bot crashed: {e}")

if __name__ == "__main__":
    t = threading.Thread(target=bot_thread, daemon=True)
    t.start()
    log.info("✅ Bot thread started")
    log.info(f"✅ HTTP server starting on port {PORT}")
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()
