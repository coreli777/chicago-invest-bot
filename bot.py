import os
import logging
import httpx
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_SEARCH_ID = os.environ.get("GOOGLE_SEARCH_ID")
CHAT_ID = os.environ.get("CHAT_ID", "7037686908")

SYSTEM_PROMPT = """Ты — профессиональный риелтор и инвестиционный консультант по недвижимости в Чикаго.

КРИТЕРИИ ИНВЕСТОРА:
- Бюджет: до $700,000
- Тип: многоквартирные дома (multifamily)
- Цель: сдача в аренду
- Локация: Чикаго и пригороды
- Обязательно: отдельные счётчики на каждый юнит (individual utility meters)

БАЗА ДАННЫХ РАЙОНОВ ЧИКАГО:

🟢 ОТЛИЧНЫЕ РАЙОНЫ ДЛЯ ИНВЕСТИЦИЙ:
- Pilsen: $350-500K, активная джентрификация. Cap Rate 5-7%. Перспективы: ВЫСОКИЕ
- Logan Square: $400-600K, высокий спрос на аренду. Cap Rate 4-6%. Перспективы: ВЫСОКИЕ
- Avondale: $300-450K, рядом с Logan Square. Cap Rate 5-7%. Перспективы: ВЫСОКИЕ
- Bridgeport: $250-400K, стабильный район. Cap Rate 6-8%. Перспективы: СРЕДНИЕ
- McKinley Park: $250-380K, тихий район. Cap Rate 6-8%. Перспективы: СРЕДНИЕ

🟡 ХОРОШИЕ РАЙОНЫ:
- Wicker Park: $500-700K, престижный. Cap Rate 3-5%. Перспективы: СРЕДНИЕ
- Bucktown: $500-700K, стабильный. Cap Rate 3-5%. Перспективы: СРЕДНИЕ
- Ukrainian Village: $400-600K, популярный. Cap Rate 4-6%. Перспективы: СРЕДНИЕ
- Irving Park: $300-500K, семьи. Cap Rate 5-7%. Перспективы: СРЕДНИЕ
- Albany Park: $280-420K, доступный. Cap Rate 6-8%. Перспективы: СРЕДНИЕ

🔴 ОСТОРОЖНО:
- Englewood: высокая преступность. Не рекомендуется
- Austin: высокая вакансия и преступность
- Roseland: сложный рынок аренды

ПРИГОРОДЫ:
- Evanston: $400-600K, университетский город
- Oak Park: $350-550K, исторический
- Berwyn: $200-350K, растущий рынок
- Cicero: $150-280K, высокая доходность

ШАБЛОН АНАЛИЗА ОБЪЕКТА:
🏢 АДРЕС: [адрес]
💰 ЦЕНА: [цена]
🛏️ UNITS: [количество]
📍 РАЙОН: [характеристика]
📊 АНАЛИЗ:
  - Цена за unit: [расчёт]
  - Аренда в месяц: [расчёт]
  - GRM: [расчёт]
  - Cap Rate: [расчёт]
  - Счётчики: [отдельные/общие]
✅/❌ ПОДХОДИТ критериям
⚠️ Без отдельных счётчиков — НЕ ПОДХОДИТ
ПРИЧИНА и РЕКОМЕНДАЦИЯ

Когда получаешь данные из автопоиска — анализируй каждый объект по шаблону выше.
Отвечай на языке пользователя."""

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
conversations = {}

async def fetch_url(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            return f"Содержимое страницы:\n{r.text[:5000]}"
    except Exception as e:
        return f"Не удалось загрузить ссылку: {e}"

async def search_new_listings(context):
    print("🔍 Searching Zillow & Redfin...")

    # Ищем именно на Zillow и Redfin
    queries = [
        "site:zillow.com multifamily Chicago IL 60000 700000",
        "site:zillow.com \"multi family\" Chicago for sale under 700000",
        "site:redfin.com multifamily Chicago IL for sale",
        "site:realtor.com multi-family Chicago IL price-700000",
    ]

    found = []
    async with httpx.AsyncClient(timeout=15) as c:
        for query in queries:
            try:
                r = await c.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": GOOGLE_API_KEY,
                        "cx": GOOGLE_SEARCH_ID,
                        "q": query,
                        "num": 3,
                    }
                )
                data = r.json()
                items = data.get("items", [])
                print(f"Query '{query[:40]}...' → {len(items)} results")

                for item in items:
                    link = item.get("link", "")
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")

                    # Фильтруем только объявления о продаже
                    if any(kw in link.lower() or kw in title.lower() or kw in snippet.lower()
                           for kw in ["for-sale", "for sale", "homedetails", "realestateandhomes"]):
                        found.append(item)

            except Exception as e:
                print(f"Search error: {e}")

    if found:
        # Убираем дубли по ссылке
        seen = set()
        unique = []
        for item in found:
            link = item.get("link", "")
            if link not in seen:
                seen.add(link)
                unique.append(item)

        msg = "🏠 <b>НАЙДЕНЫ НОВЫЕ ОБЪЕКТЫ В ЧИКАГО!</b>\n\n"
        for i, item in enumerate(unique[:5], 1):
            title = item.get("title", "")[:60]
            snippet = item.get("snippet", "")[:120]
            link = item.get("link", "")
            msg += f"{i}. <b>{title}</b>\n"
            msg += f"   {snippet}\n"
            msg += f"   🔗 <a href='{link}'>Открыть объявление</a>\n\n"

        msg += "💡 Отправьте ссылку боту для детального анализа!"

        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        print(f"✅ Sent {len(unique)} listings to Telegram")
    else:
        print("⚠️ No listings found this round")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in conversations:
        conversations[user_id] = []

    urls = [w for w in text.split() if w.startswith("http")]

    if len(urls) > 1:
        await update.message.reply_text(f"📊 Нашёл {len(urls)} объекта — анализирую...")
        pages = ""
        for i, url in enumerate(urls, 1):
            content = await fetch_url(url)
            pages += f"\n\n=== ОБЪЕКТ {i} ===\n{content}"
        text = f"Сравни эти объекты:\n{pages}"
    elif len(urls) == 1:
        await update.message.reply_text("🔍 Анализирую объект...")
        content = await fetch_url(urls[0])
        text = f"Проанализируй:\n{urls[0]}\n{content}"

    conversations[user_id].append({"role": "user", "content": text})
    if len(conversations[user_id]) > 20:
        conversations[user_id] = conversations[user_id][-20:]

    await update.message.chat.send_action("typing")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=conversations[user_id]
    )
    reply = response.content[0].text
    conversations[user_id].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Bot is running!")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"✅ Health server on port {port}")
    server.serve_forever()

def main():
    # Запускаем HTTP сервер в отдельном потоке (требование Cloud Run)
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Поиск каждые 30 минут
    app.job_queue.run_repeating(search_new_listings, interval=1800, first=10)

    print("🚀 Бот запущен! Автопоиск каждые 30 минут.")
    app.run_polling()

if __name__ == "__main__":
    main()
