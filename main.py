import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")

# Payment details
CBE_ACCOUNT = "1000647705808"
CBE_NAME = "Yosef"
TELEBIRR_NUMBER = "0967523107"
TELEBIRR_NAME = "Yosef"
PRICE = "200 ETB"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# DeepSeek client
client = OpenAI(api_key="sk-9681a031a1724260b293283f47438bd2", base_url="https://api.deepseek.com")

# System prompt for AI
SYSTEM_PROMPT = """You are a helpful assistant for Ethiopian university students. Your name is Campus Guide.

Your purpose:
- Help students choose the right university department
- Provide information about job outlook, salary ranges, AI risk, and career paths
- Guide students on how to pay for full access (200 ETB via CBE or Telebirr)

Payment information:
- CBE Birr: 1000647705808 (Yosef)
- Telebirr: 0967523107 (Yosef)
- Amount: 200 ETB

If a user asks about payment or wants to unlock full access, explain the payment options and ask them to upload a screenshot after payment.

If a user is not a paid member, politely explain that full department details require a one-time payment of 200 ETB.

Keep responses friendly, concise, and helpful. Use Ethiopian Birr (ETB) for all prices."""

# --- Helper Functions ---
async def is_user_in_paid_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PAID_GROUP_ID:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=PAID_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def get_deepseek_response(user_message: str, is_paid: bool) -> str:
    try:
        # Add payment status to context
        context_note = ""
        if not is_paid:
            context_note = "\n\n[Note: This user has NOT paid yet. Encourage them to pay 200 ETB for full access to detailed department information.]"
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + context_note},
                {"role": "user", "content": user_message}
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return "Sorry, I'm having trouble right now. Please try again in a moment."

# --- Handle All Text Messages (AI Response) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Check payment status
    is_paid = await is_user_in_paid_group(user_id, context)
    
    # Show typing indicator
    await update.message.chat.send_action(action="typing")
    
    # Get AI response
    ai_response = await get_deepseek_response(user_message, is_paid)
    await update.message.reply_text(ai_response)

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
                 f"After joining, you can ask me anything about any department!"
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

    # Only message handlers - NO commands
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))

    logger.info("Starting AI assistant...")
    app.run_polling()

if __name__ == "__main__":
    main()
