import os
import logging
import httpx
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

КОГДА АНАЛИЗИРУЕШЬ НЕДВИЖИМОСТЬ ПО ССЫЛКЕ — отвечай по этому шаблону:

🏢 АДРЕС: [адрес]
💰 ЦЕНА: [цена]
🛏️ UNITS: [количество квартир]
📊 АНАЛИЗ:
  - Цена за unit: [расчёт]
  - Примерная аренда в месяц: [расчёт]
  - Gross Rent Multiplier: [расчёт]
  - - Cap Rate (примерный): [расчёт]
  - Счётчики: [отдельные на каждый юнит / общие]

✅ ПОДХОДИТ / ❌ НЕ ПОДХОДИТ критериям инвестора
⚠️ ВАЖНО: Без отдельных счётчиков на каждый юнит — НЕ ПОДХОДИТ

ПРИЧИНА: [объяснение]

РЕКОМЕНДАЦИЯ: [что делать дальше]

Если пользователь просто задаёт вопрос — отвечай как профессиональный консультант.
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

    url = extract_url(text)
    if url:
        await update.message.reply_text("🔍 Читаю ссылку и анализирую...")
        page_content = await fetch_url(url)
        text = f"Проанализируй эту недвижимость по моим критериям инвестора:\n{url}\n\n{page_content}"

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

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()