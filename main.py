import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")

PORT = int(os.environ.get("PORT", 8080))

# Your Railway domain
RAILWAY_DOMAIN = "deepseek-bot-production.up.railway.app"

# Payment details
CBE_ACCOUNT = "1000647705808"
CBE_NAME = "Yosef"
TELEBIRR_NUMBER = "0967523107"
TELEBIRR_NAME = "Yosef"
PRICE = "200 ETB"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# DeepSeek client with hardcoded key
client = OpenAI(api_key="sk-9681a031a1724260b293283f47438bd2", base_url="https://api.deepseek.com")

# --- Helper Functions ---
async def is_user_in_paid_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PAID_GROUP_ID:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=PAID_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def get_deepseek_response(user_message: str) -> str:
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for Ethiopian university students. Answer questions about departments, job outlook, salary, AI risk, and career paths. Keep answers concise and helpful."},
                {"role": "user", "content": user_message}
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return "Sorry, I'm having trouble connecting to my knowledge base. Please try again later."

# --- Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 *Welcome to Campus Department Guide!*\n\n"
        "I help Ethiopian students choose the right university department.\n\n"
        "*Commands:*\n"
        "/pay - Unlock full access (200 ETB)\n"
        "/status - Check your subscription\n"
        "/help - Get support\n\n"
        "Ask me anything about departments, job outlook, or career paths!",
        parse_mode="Markdown"
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "💳 *Payment Options*\n\n"
        f"🇪🇹 *CBE Birr*\n"
        f"Account: `{CBE_ACCOUNT}`\n"
        f"Name: {CBE_NAME}\n\n"
        f"📱 *Telebirr*\n"
        f"Number: `{TELEBIRR_NUMBER}`\n"
        f"Name: {TELEBIRR_NAME}\n\n"
        f"💰 *Amount:* {PRICE}\n\n"
        "📸 *After payment:*\n"
        "Upload your payment screenshot here.\n"
        "You will be added to the paid group within 1 hour."
    )
    await update.message.reply_text(message, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_user_in_paid_group(user_id, context):
        await update.message.reply_text("✅ You have active paid access.")
    else:
        await update.message.reply_text("❌ You do not have paid access. Use /pay to unlock.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Campus Department Guide Help*\n\n"
        "*Free Features:*\n"
        "• Browse department previews in our channel\n\n"
        "*Paid Features (200 ETB):*\n"
        "• Ask me anything about any department\n"
        "• Get salary ranges, AI risk scores, job outlook\n"
        "• Masters pathways and NGO opportunities\n\n"
        "Use /pay to unlock full access.",
        parse_mode="Markdown"
    )

# --- Handle Messages (AI Response) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_message.startswith('/'):
        return

    if await is_user_in_paid_group(user_id, context):
        await update.message.chat.send_action(action="typing")
        ai_response = await get_deepseek_response(user_message)
        await update.message.reply_text(ai_response)
    else:
        await update.message.reply_text(
            "🔒 This assistant is for paid members only.\n"
            "Use /pay to unlock full access (200 ETB)."
        )

# --- Handle Payment Screenshots ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]

    keyboard = [[InlineKeyboardButton(
        f"✅ Approve @{user.username or user.id}", 
        callback_data=f"approve_{user.id}"
    )]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_photo(
        chat_id=ADMIN_CHANNEL_ID,
        photo=photo.file_id,
        caption=f"📸 Payment proof from @{user.username or user.id}\nUser ID: `{user.id}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    await update.message.reply_text(
        "✅ Payment screenshot received!\n"
        "You will be added to the paid group within 1 hour after verification."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document = update.message.document

    keyboard = [[InlineKeyboardButton(
        f"✅ Approve @{user.username or user.id}", 
        callback_data=f"approve_{user.id}"
    )]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_document(
        chat_id=ADMIN_CHANNEL_ID,
        document=document.file_id,
        caption=f"📎 Payment proof from @{user.username or user.id}\nUser ID: `{user.id}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ Payment document received! You will be added within 1 hour.")

# --- Admin Approve Callback ---
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.replace("approve_", ""))

    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID,
            member_limit=1
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your payment has been verified!\n\n"
                 f"🔗 Join the paid group here (one-time use):\n{invite_link.invite_link}\n\n"
                 f"After joining, you can ask me questions about any department!"
        )

        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ APPROVED by admin"
        )

    except Exception as e:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ Error: {e}"
        )

# --- Main ---
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))

    logger.info(f"Starting webhook on port {PORT}...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://{RAILWAY_DOMAIN}/webhook"
    )

if __name__ == "__main__":
    main()
