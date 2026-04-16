import os
import logging
import httpx
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY")
SYSTEM_PROMPT = """Ты — профессиональный риелтор и инвестиционный консультант по недвижимости в Чикаго.

КРИТЕРИИ ИНВЕСТОРА:
- Бюджет: до $700,000
- Тип: многоквартирные дома (multifamily)
- Цель: сдача в аренду
- Локация: Чикаго и пригороды
- Обязательно: отдельные счётчики на каждый юнит (individual utility meters)

БАЗА ДАННЫХ РАЙОНОВ ЧИКАГО:

🟢 ОТЛИЧНЫЕ РАЙОНЫ ДЛЯ ИНВЕСТИЦИЙ:
- Pilsen: Средняя цена $350-500K, активная джентрификация, молодёжь, артисты. Cap Rate 5-7%. Перспективы роста: ВЫСОКИЕ
- Logan Square: $400-600K, хипстерский район, высокий спрос на аренду. Cap Rate 4-6%. Перспективы: ВЫСОКИЕ
- Avondale: $300-450K, рядом с Logan Square, более доступный. Cap Rate 5-7%. Перспективы: ВЫСОКИЕ
- Bridgeport: $250-400K, стабильный рабочий район, низкая вакансия. Cap Rate 6-8%. Перспективы: СРЕДНИЕ
- McKinley Park: $250-380K, тихий район, семьи. Cap Rate 6-8%. Перспективы: СРЕДНИЕ

🟡 ХОРОШИЕ РАЙОНЫ:
- Wicker Park: $500-700K, престижный, высокая аренда. Cap Rate 3-5%. Перспективы: СРЕДНИЕ
- Bucktown: $500-700K, дорогой, стабильный. Cap Rate 3-5%. Перспективы: СРЕДНИЕ
- Ukrainian Village: $400-600K, популярный, артистичный. Cap Rate 4-6%. Перспективы: СРЕДНИЕ
- Irving Park: $300-500K, транспортная доступность, семьи. Cap Rate 5-7%. Перспективы: СРЕДНИЕ
- Albany Park: $280-420K, разнообразный район, доступный. Cap Rate 6-8%. Перспективы: СРЕДНИЕ

🔴 ОСТОРОЖНО:
- Englewood: Низкие цены но высокая преступность. Не рекомендуется
- Austin: Доступный но высокая вакансия и преступность
- Roseland: Низкие цены, сложный рынок аренды

ПРИГОРОДЫ ЧИКАГО ДЛЯ ИНВЕСТИЦИЙ:
- Evanston: $400-600K, университетский город, стабильная аренда
- Oak Park: $350-550K, историческая архитектура, семьи
- Berwyn: $200-350K, доступный, растущий рынок
- Cicero: $150-280K, очень доступный, высокая доходность

КОГДА АНАЛИЗИРУЕШЬ НЕДВИЖИМОСТЬ ПО ССЫЛКЕ — отвечай по этому шаблону:

🏢 АДРЕС: [адрес]
💰 ЦЕНА: [цена]
🛏️ UNITS: [количество квартир]
📍 РАЙОН: [название района + характеристика из базы данных]
📊 АНАЛИЗ:
  - Цена за unit: [расчёт]
  - Примерная аренда в месяц: [расчёт]
  - Gross Rent Multiplier: [расчёт]
  - Cap Rate (примерный): [расчёт]
  - Счётчики: [отдельные / общие]

✅ ПОДХОДИТ / ❌ НЕ ПОДХОДИТ критериям инвестора

⚠️ ВАЖНО: Без отдельных счётчиков на каждый юнит — НЕ ПОДХОДИТ

ПРИЧИНА: [объяснение]
РЕКОМЕНДАЦИЯ: [что делать дальше]

Если пользователь спрашивает о районе — дай детальную информацию из базы данных.
Отвечай на языке пользователя (русский или английский)."""

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
conversations = {}

async def fetch_url(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            text = r.text[:5000]
            return f"Содержимое страницы:\n{text}"
    except Exception as e:
        return f"Не удалось загрузить ссылку: {e}"

def extract_url(text: str) -> str:
    for word in text.split():
        if word.startswith("http://") or word.startswith("https://"):
            return word
    return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in conversations:
        conversations[user_id] = []

    # Находим все ссылки в сообщении
    urls = [word for word in text.split() if word.startswith("http://") or word.startswith("https://")]

    if len(urls) > 1:
        # Несколько ссылок — режим сравнения
        await update.message.reply_text(f"📊 Нашёл {len(urls)} объекта — анализирую и сравниваю...")
        
        pages_content = ""
        for i, url in enumerate(urls, 1):
            content = await fetch_url(url)
            pages_content += f"\n\n=== ОБЪЕКТ {i}: {url} ===\n{content}"

        text = f"Сравни эти {len(urls)} объекта недвижимости по моим критериям инвестора. Для каждого сделай краткий анализ, потом дай итоговую таблицу сравнения и скажи какой лучше всего подходит:\n{pages_content}"

    elif len(urls) == 1:
        # Одна ссылка — обычный анализ
        await update.message.reply_text("🔍 Читаю ссылку и анализирую...")
        page_content = await fetch_url(urls[0])
        text = f"Проанализируй эту недвижимость по моим критериям инвестора:\n{urls[0]}\n\n{page_content}"

    conversations[user_id].append({
        "role": "user",
        "content": text
    })

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

    conversations[user_id].append({
        "role": "assistant",
        "content": reply
    })

    await update.message.reply_text(reply)
async def search_new_listings(context):
    google_key = os.environ.get("GOOGLE_API_KEY")
    search_id  = os.environ.get("GOOGLE_SEARCH_ID")
    bot_token  = os.environ.get("TELEGRAM_TOKEN")
    chat_id    = "7037686908"

    queries = [
        "multifamily for sale Chicago under 700000 site:redfin.com",
        "multifamily for sale Chicago under 700000 site:loopnet.com",
    ]

    found = []
    async with httpx.AsyncClient() as client:
        for query in queries:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": google_key,
                "cx": search_id,
                "q": query,
                "num": 3,
                "dateRestrict": "d1"
            }
            try:
                r = await client.get(url, params=params)
                data = r.json()
                items = data.get("items", [])
                for item in items:
                    found.append({
                        "title": item.get("title"),
                        "link": item.get("link"),
                        "snippet": item.get("snippet")
                    })
            except Exception as e:
                print(f"Search error: {e}")

    if found:
        msg = "🏠 <b>НОВЫЕ ОБЪЕКТЫ В ЧИКАГО!</b>\n\n"
        for i, item in enumerate(found[:5], 1):
            msg += f"{i}. <b>{item['title']}</b>\n"
            msg += f"   {item['snippet'][:100]}...\n"
            msg += f"   🔗 {item['link']}\n\n"

        send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(send_url, json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "HTML"
            })

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_repeating(search_new_listings, interval=21600, first=10)

    print("🚀 Бот запущен!")
    app.run_polling()