import os
import logging
import aiohttp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")

# Gemini API (SAFE)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Your personal Telegram ID
ADMIN_USER_ID = 8228561129

# Payment details
TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# System prompt
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

Keep responses concise and helpful. Use Ethiopian Birr (ETB).
"""

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
    if not GEMINI_API_KEY:
        return "API key not configured."

    try:
        context_note = ""
        if not is_paid:
            context_note = f"\n\n[User not paid. Encourage payment of {PRICE}]"

        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{SYSTEM_PROMPT}\n\n{context_note}\n\nStudent question: {user_message}"
                }]
            }]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload
            ) as resp:
                data = await resp.json()

                if "candidates" in data:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                elif "error" in data:
                    return f"API Error: {data['error']['message']}"
                else:
                    return "Unexpected response."

    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "Service error. Try again."


# --- Message Handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    is_paid = await is_user_in_paid_group(user_id, context)

    await update.message.chat.send_action(action="typing")
    ai_response = await get_gemini_response(user_message, is_paid)
    await update.message.reply_text(ai_response)


# --- Payment Handlers ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]

    keyboard = [[InlineKeyboardButton(
        f"Approve @{user.username or user.id}",
        callback_data=f"approve_{user.id}"
    )]]

    await context.bot.send_photo(
        chat_id=ADMIN_USER_ID,
        photo=photo.file_id,
        caption=f"Payment proof from @{user.username or user.id}\nID: {user.id}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await update.message.reply_text("Screenshot received. Wait for approval.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document = update.message.document

    keyboard = [[InlineKeyboardButton(
        f"Approve @{user.username or user.id}",
        callback_data=f"approve_{user.id}"
    )]]

    await context.bot.send_document(
        chat_id=ADMIN_USER_ID,
        document=document.file_id,
        caption=f"Payment proof from @{user.username or user.id}\nID: {user.id}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await update.message.reply_text("Document received. Wait for approval.")


# --- Approve ---
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.replace("approve_", ""))

    invite_link = await context.bot.create_chat_invite_link(
        chat_id=PAID_GROUP_ID,
        member_limit=1
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=f"Payment verified.\nJoin:\n{invite_link.invite_link}"
    )

    await query.edit_message_caption(
        caption=f"{query.message.caption}\n\nAPPROVED"
    )


# --- Main ---
def main():
    if not TELEGRAM_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))

    app.run_polling()


if __name__ == "__main__":
    main()
