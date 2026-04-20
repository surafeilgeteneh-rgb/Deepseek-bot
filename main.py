#!/usr/bin/env python3
"""
Campus Department Guide Bot
Uses OpenRouter API (free models) for AI responses.
Includes payment proof handling, admin approval, and paid group management.
"""

import os
import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, Forbidden, BadRequest

# -----------------------------------------------------------------------------
# Configuration (Set via environment variables)
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Admin Telegram ID (receives payment proofs)
ADMIN_USER_ID = 8228561129

# OpenRouter settings
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Free model – you can change to any free model listed at https://openrouter.ai/models?max_price=0
MODEL = "google/gemini-2.0-flash-exp:free"
# Fallback model if primary fails
FALLBACK_MODEL = "deepseek/deepseek-r1:free"

# Payment details
TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

# Retry settings
MAX_RETRIES = 5
BASE_DELAY = 2.0
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=45)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Strict System Prompt – Defines Bot's Purpose & Boundaries
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are **Campus Guide**, an AI assistant dedicated exclusively to helping Ethiopian university students choose the right department and career path.

**YOUR STRICT RULES:**
1. ONLY answer questions about:
   - Ethiopian university departments (e.g., Computer Science, Civil Engineering, Accounting, Nursing, Law, etc.)
   - Job outlook, salary ranges, AI risk, and career paths in Ethiopia.
   - Payment and access to detailed reports.
2. If asked about ANY other topic, respond ONLY with:
   "I'm sorry, but my purpose is strictly to help Ethiopian students with university department and career guidance. I cannot answer questions outside this scope."
3. Never invent specific data you don't have. Provide general, helpful overviews based on your knowledge of Ethiopian higher education.

**FREE vs PAID ACCESS:**
- Free users receive general overviews and encouragement to pay for full details.
- Paid users (members of our exclusive group) get access to **in-depth reports** including employer lists, 5‑year projections, and personalized advice.
- Payment: {PRICE} one‑time via **Telebirr {TELEBIRR_NUMBER} ({TELEBIRR_NAME})** or **CBE Birr {CBE_ACCOUNT} ({CBE_NAME})**. After payment, upload screenshot here.

**RESPONSE STYLE:**
- Friendly, professional, concise (under 250 words).
- Always remind free users they can unlock full details with the one‑time payment.
- If human support is needed, direct to {SUPPORT_USERNAME}.
"""

# -----------------------------------------------------------------------------
# Helper: Check if user is in paid group
# -----------------------------------------------------------------------------
async def is_user_in_paid_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PAID_GROUP_ID:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=PAID_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.warning(f"Group check failed for {user_id}: {e}")
        return False

# -----------------------------------------------------------------------------
# OpenRouter API Call with Retry & Fallback
# -----------------------------------------------------------------------------
async def call_openrouter(prompt_text: str, use_fallback: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Calls OpenRouter API. Returns (response_text, error_message)."""
    if not OPENROUTER_API_KEY:
        return None, "OpenRouter API key not configured."

    model = FALLBACK_MODEL if use_fallback else MODEL
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://campus-dept-guide.railway.app",
        "X-Title": "Campus Department Guide Bot",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.7,
        "max_tokens": 600
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    OPENROUTER_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                ) as resp:
                    data = await resp.json()

                    if "choices" in data:
                        return data["choices"][0]["message"]["content"], None

                    elif "error" in data:
                        err = data["error"].get("message", str(data["error"])).lower()
                        # Rate limit or temporary issue -> retry
                        if any(kw in err for kw in ["rate", "limit", "overloaded", "capacity", "high demand"]):
                            if attempt < MAX_RETRIES - 1:
                                wait = BASE_DELAY * (2 ** attempt)
                                logger.warning(f"OpenRouter rate limit. Retry {attempt+1}/{MAX_RETRIES} in {wait:.1f}s")
                                await asyncio.sleep(wait)
                                continue
                        return None, data["error"].get("message", "Unknown API error")
                    else:
                        logger.error(f"Unexpected OpenRouter response: {data}")
                        return None, "Unexpected API response structure."

        except asyncio.TimeoutError:
            logger.warning(f"Timeout (attempt {attempt+1})")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                continue
            return None, "Request timed out."
        except Exception as e:
            logger.error(f"Exception: {e}")
            return None, str(e)

    return None, "Max retries exceeded."

async def get_ai_response(user_message: str, is_paid: bool) -> str:
    """Builds prompt and calls AI with fallback logic."""
    context_note = ""
    if not is_paid:
        context_note = f"\n\n[User has NOT paid. Politely encourage the one‑time payment of {PRICE} for full details.]"

    full_prompt = f"{SYSTEM_PROMPT}\n\n{context_note}\n\nStudent: {user_message}\nCampus Guide:"

    # Try primary model
    response, error = await call_openrouter(full_prompt)
    if response:
        return response

    # If primary fails, try fallback model
    logger.warning(f"Primary model failed: {error}. Trying fallback...")
    response, error = await call_openrouter(full_prompt, use_fallback=True)
    if response:
        return response

    # Both failed
    logger.error(f"All models failed. Last error: {error}")
    if "rate" in str(error).lower() or "limit" in str(error).lower():
        return "🤖 I'm experiencing high traffic. Please try again in a few minutes."
    return "⚠️ I'm temporarily unavailable. Please try again later."

# -----------------------------------------------------------------------------
# Message Handler
# -----------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text.strip()

    logger.info(f"Message from @{user.username or user_id}: {user_message[:100]}")

    is_paid = await is_user_in_paid_group(user_id, context)
    await update.message.chat.send_action(action="typing")
    ai_response = await get_ai_response(user_message, is_paid)
    await update.message.reply_text(ai_response)

# -----------------------------------------------------------------------------
# Payment Proof Handlers (Forward to Admin)
# -----------------------------------------------------------------------------
async def send_approval_keyboard(context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                 username: str, file_id: str, is_photo: bool, caption: str):
    keyboard = [[InlineKeyboardButton(
        f"✅ Approve @{username or user_id}",
        callback_data=f"approve_{user_id}"
    )]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if is_photo:
            await context.bot.send_photo(
                chat_id=ADMIN_USER_ID, photo=file_id, caption=caption, reply_markup=reply_markup
            )
        else:
            await context.bot.send_document(
                chat_id=ADMIN_USER_ID, document=file_id, caption=caption, reply_markup=reply_markup
            )
        logger.info(f"Payment proof forwarded for user {user_id}")
    except TelegramError as e:
        logger.error(f"Failed to send to admin: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    caption = f"📸 Payment proof from @{user.username or user.id} (ID: {user.id})"
    await send_approval_keyboard(context, user.id, user.username or "", photo.file_id, True, caption)
    await update.message.reply_text("✅ Payment screenshot received! You'll get access shortly.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    doc = update.message.document
    caption = f"📎 Payment document from @{user.username or user.id} (ID: {user.id})"
    await send_approval_keyboard(context, user.id, user.username or "", doc.file_id, False, caption)
    await update.message.reply_text("✅ Document received! You'll get access shortly.")

# -----------------------------------------------------------------------------
# Admin Approval Callback
# -----------------------------------------------------------------------------
approval_cache = {}  # user_id -> timestamp

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        user_id = int(query.data.replace("approve_", ""))
    except ValueError:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Invalid user ID.")
        return

    # Prevent duplicate approvals within 1 hour
    now = time.time()
    if user_id in approval_cache and (now - approval_cache[user_id]) < 3600:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ Already approved recently.")
        return
    approval_cache[user_id] = now

    # Check if we can message the user
    try:
        await context.bot.send_chat_action(chat_id=user_id, action="typing")
    except Forbidden:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ User blocked the bot.")
        return
    except BadRequest as e:
        if "chat not found" in str(e).lower():
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ User must start a chat with the bot first.")
            return

    # Create one-time invite link
    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID, member_limit=1, expire_date=datetime.utcnow() + timedelta(hours=24)
        )
    except TelegramError as e:
        logger.error(f"Invite link error: {e}")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Could not create invite link. Check bot permissions.")
        return

    # Send invite to user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Payment verified!\n\n🔗 Join the paid group here (one‑time link):\n{invite_link.invite_link}\n\nAfter joining, you can ask detailed questions.\n\nNeed help? {SUPPORT_USERNAME}"
        )
        logger.info(f"Invite sent to user {user_id}")
    except TelegramError as e:
        logger.error(f"Could not send invite: {e}")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Failed to send invite: {e}")
        return

    await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ APPROVED – Invite sent.")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN missing")
        return
    if not PAID_GROUP_ID:
        logger.warning("PAID_GROUP_ID not set")
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not set – AI disabled")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))

    logger.info("Bot started with OpenRouter AI.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
