import os
import logging
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")

# Payment details
TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

# Gemini API
GEMINI_API_KEY = "AIzaSyA2fx0F9XUXFligheoVNL_x3yVFHkiJKBg"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# System prompt for AI
SYSTEM_PROMPT = f"""You are a helpful assistant for Ethiopian university students. Your name is Campus Guide.

Your purpose:
- Help students choose the right university department
- Provide information about job outlook, salary ranges, AI risk, and career paths
- Guide students on how to pay for full access (70 ETB via CBE or Telebirr)

Payment information:
- Telebirr: {TELEBIRR_NUMBER} ({TELEBIRR_NAME})
- CBE Birr: {CBE_ACCOUNT} ({CBE_NAME})
- Amount: {PRICE}

If a user asks about payment or wants to unlock full access, explain the payment options and ask them to upload a screenshot after payment.

If a user is not a paid member, politely explain that full department details require a one-time payment of {PRICE}.

If a user needs human support, direct them to contact {SUPPORT_USERNAME} on Telegram.

Keep responses friendly, concise, and helpful. Use Ethiopian Birr (ETB) for all prices."""

# --- Helper Functions ---
async def is_user_in_paid_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PAID_GROUP_ID:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=PAID_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Group check error: {e}")
        return False

async def get_gemini_response(user_message: str, is_paid: bool) -> str:
    try:
        context_note = ""
        if not is_paid:
            context_note = f"\n\n[Note: This user has NOT paid yet. Encourage them to pay {PRICE} for full access to detailed department information.]"
        
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{SYSTEM_PROMPT}\n\n{context_note}\n\nStudent question: {user_message}"
                }]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 500
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload
            ) as resp:
                data = await resp.json()
                
                if "candidates" in data and len(data["candidates"]) > 0:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                elif "error" in data:
                    logger.error(f"Gemini API error: {data['error']}")
                    return f"API Error: {data['error']['message']}"
                else:
                    logger.error(f"Unexpected Gemini response: {data}")
                    return "Sorry, I received an unexpected response. Please try again."
                    
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return "Sorry, I'm having trouble right now. Please try again in a moment."

# --- Handle All Text Messages ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        user_message = update.message.text
        
        logger.info(f"Received message from {user_id}: {user_message[:50]}...")
        
        is_paid = await is_user_in_paid_group(user_id, context)
        logger.info(f"User {user_id} paid status: {is_paid}")
        
        await update.message.chat.send_action(action="typing")
        ai_response = await get_gemini_response(user_message, is_paid)
        await update.message.reply_text(ai_response)
        
    except Exception as e:
        logger.error(f"Message handling error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")

# --- Handle Payment Screenshots ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Photo handling error: {e}")
        await update.message.reply_text("Error processing image. Please try again.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Document handling error: {e}")
        await update.message.reply_text("Error processing file. Please try again.")

# --- Admin Approve Callback ---
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        user_id = int(query.data.replace("approve_", ""))
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID,
            member_limit=1
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your payment has been verified!\n\n"
                 f"🔗 Join the paid group here (one-time use):\n{invite_link.invite_link}\n\n"
                 f"After joining, you can ask me anything about any department!\n\n"
                 f"Need help? Contact {SUPPORT_USERNAME}"
        )

        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ APPROVED by admin"
        )

    except Exception as e:
        logger.error(f"Approve callback error: {e}")
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ Error: {e}"
        )

# --- Main ---
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))

    logger.info("Starting AI assistant with Gemini REST API...")
    app.run_polling()

if __name__ == "__main__":
    main()
