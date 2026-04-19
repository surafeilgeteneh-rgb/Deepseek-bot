import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # Your Telegram user ID

PORT = int(os.environ.get("PORT", 8080))

# Payment details
CBE_ACCOUNT = "1000647705808"
CBE_NAME = "Yosef"
TELEBIRR_NUMBER = "0967523107"
TELEBIRR_NAME = "Yosef"
PRICE = "200 ETB"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

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
                {"role": "system", "content": "You are a helpful assistant for Ethiopian university students. Answer questions about departments, job outlook, salary, AI risk, and career paths. Keep answers concise."},
                {"role": "user", "content": user_message}
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return "Sorry, I'm having trouble connecting to my knowledge base."

# --- Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 *Welcome to Campus Department Guide!*\n\n"
        "/pay - Unlock full access (200 ETB)\n"
        "/status - Check your subscription\n"
        "/help - Get support",
        parse_mode="Markdown"
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "💳 *Payment Options*\n\n"
        f"🇪🇹 *CBE Birr*\nAccount: `{CBE_ACCOUNT}`\nName: {CBE_NAME}\n\n"
        f"📱 *Telebirr*\nNumber: `{TELEBIRR_NUMBER}`\nName: {TELEBIRR_NAME}\n\n"
        f"💰 *Amount:* {PRICE}\n\n"
        "📸 *After payment:* Upload screenshot here."
    )
    await update.message.reply_text(message, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_user_in_paid_group(user_id, context):
        await update.message.reply_text("✅ You have active paid access.")
    else:
        await update.message.reply_text("❌ No paid access. Use /pay.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 Ask me about departments, salary, AI risk, or job outlook. Use /pay for full access.")

# --- AI Response for Paid Users ---
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
        await update.message.reply_text("🔒 Paid members only. Use /pay.")

# --- Handle Payment Screenshots (Forward to YOU) ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]

    # Forward to you (admin)
    if ADMIN_ID:
        keyboard = [[InlineKeyboardButton(
            f"✅ Approve @{user.username or user.id}", 
            callback_data=f"approve_{user.id}"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo.file_id,
            caption=f"📸 Payment from @{user.username or user.id}\nID: `{user.id}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    await update.message.reply_text("✅ Screenshot received. You'll be added within 1 hour.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document = update.message.document

    if ADMIN_ID:
        keyboard = [[InlineKeyboardButton(
            f"✅ Approve @{user.username or user.id}", 
            callback_data=f"approve_{user.id}"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=document.file_id,
            caption=f"📎 Payment from @{user.username or user.id}\nID: `{user.id}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    await update.message.reply_text("✅ Document received. You'll be added within 1 hour.")

# --- Admin Approve Button ---
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
            text=f"✅ Payment verified!\n\n🔗 Join here (one-time use):\n{invite_link.invite_link}"
        )

        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ APPROVED"
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

    logger.info("Starting webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN')}/webhook"
    )

if __name__ == "__main__":
    main()
