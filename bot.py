import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY")

SYSTEM_PROMPT = """Ты — профессиональный риелтор и инвестиционный консультант по недвижимости в Чикаго.

Ты помогаешь клиентам:
- Найти недвижимость для инвестиций в Чикаго
- Анализировать районы и их перспективы
- Рассчитывать доходность инвестиций
- Отвечать на вопросы о рынке недвижимости Чикаго

Отвечай на языке пользователя (русский или английский).
Будь профессиональным, дружелюбным и конкретным."""

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
conversations = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({
        "role": "user",
        "content": text
    })

    if len(conversations[user_id]) > 20:
        conversations[user_id] = conversations[user_id][-20:]

    await update.message.chat.send_action("typing")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
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