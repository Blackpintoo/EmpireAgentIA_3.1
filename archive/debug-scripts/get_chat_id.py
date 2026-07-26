from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = "7969631468:AAHzPL6iCB9kO0K1iPtVeTkP-L2FevVdttc"

async def show_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text=f"✅ Ton chat_id est : {chat_id}")

def main():
    app = Application.builder().token(TOKEN).build()
    # Le bot répond à TOUT ce que tu lui écris avec ton chat_id
    app.add_handler(MessageHandler(filters.ALL, show_chat_id))
    print("Bot lancé, envoie un message à ton bot Telegram !")
    app.run_polling()

if __name__ == "__main__":
    main()
