#!/usr/bin/env python3
import os
import logging
import asyncio
import time
import random
from datetime import datetime, timedelta
from typing import Optional, Tuple

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, Forbidden, BadRequest

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

ADMIN_USER_ID = 8228561129

# OpenRouter settings
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = "deepseek/deepseek-r1:free"
FALLBACK_MODEL = "google/gemini-2.0-flash-exp:free"

TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are Campus Guide, helping Ethiopian students.
Payment: {PRICE} via Telebirr {TELEBIRR_NUMBER} ({TELEBIRR_NAME}) or CBE {CBE_ACCOUNT} ({CBE_NAME}).
Keep responses under 250 words."""

# -----------------------------------------------------------------------------
async def is_user_in_paid_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PAID_GROUP_ID:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=PAID_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Group check error: {e}")
        return False

# -----------------------------------------------------------------------------
async def call_openrouter(prompt: str, use_fallback: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Calls OpenRouter with exponential backoff and jitter on rate limits."""
    model = FALLBACK_MODEL if use_fallback else MODEL
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://campus-dept-guide.railway.app",
        "X-Title": "Campus Guide Bot",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 600
    }

    attempt = 0
    max_retries = 5
    base_delay = 5

    while attempt < max_retries:
        attempt += 1
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"Attempt {attempt}: Calling OpenRouter with model: {model}")
                async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT) as resp:
                    data = await resp.json()
                    logger.info(f"OpenRouter response: {data}")

                    if "choices" in data:
                        return data["choices"][0]["message"]["content"], None

                    error = data.get("error", {})
                    error_code = error.get("code", resp.status)
                    error_msg = error.get("message", "Unknown error")

                    if error_code == 429 or "rate" in error_msg.lower() or "exhausted" in error_msg.lower():
                        if attempt == max_retries:
                            logger.error("Max retries reached for rate limit.")
                            return None, "Rate limit exceeded. Please try again later."
                        
                        # Exponential backoff with jitter
                        delay = (base_delay * (2 ** (attempt - 1))) + random.uniform(0, 2)
                        logger.warning(f"Rate limited (HTTP {error_code}). Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        continue

                    logger.error(f"OpenRouter API error (non-retryable): {error_code} - {error_msg}")
                    return None, error_msg

        except asyncio.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt}")
            if attempt < max_retries:
                await asyncio.sleep(base_delay * attempt)
                continue
            return None, "Request timed out."
        except Exception as e:
            logger.error(f"Exception on attempt {attempt}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(base_delay * attempt)
                continue
            return None, str(e)

    return None, "Max retries exceeded."

async def get_ai_response(user_message: str, is_paid: bool) -> str:
    prompt = SYSTEM_PROMPT
    if not is_paid:
        prompt += f"\n\nUser has NOT paid. Encourage {PRICE} payment."
    prompt += f"\n\nStudent: {user_message}\nCampus Guide:"

    response, error = await call_openrouter(prompt)
    if response:
        return response
    return f"⚠️ Service unavailable. Reason: {error}"

# -----------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text.strip()
    logger.info(f"✅ Message received from @{user.username or user_id}: {user_message[:100]}")

    is_paid = await is_user_in_paid_group(user_id, context)
    logger.info(f"Paid status for {user_id}: {is_paid}")

    await update.message.chat.send_action(action="typing")
    logger.info("Calling AI...")
    ai_response = await get_ai_response(user_message, is_paid)
    await update.message.reply_text(ai_response)

# -----------------------------------------------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    keyboard = [[InlineKeyboardButton(f"✅ Approve @{user.username or user.id}", callback_data=f"approve_{user.id}")]]
    await context.bot.send_photo(
        chat_id=ADMIN_USER_ID, photo=photo.file_id,
        caption=f"Payment from @{user.username or user.id} (ID: {user.id})",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✅ Received! You'll get access shortly.")

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        user_id = int(query.data.replace("approve_", ""))
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID, member_limit=1, expire_date=datetime.utcnow() + timedelta(hours=24)
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Payment verified!\n🔗 Join: {invite_link.invite_link}\nSupport: {SUPPORT_USERNAME}"
        )
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ APPROVED")
    except (Forbidden, BadRequest) as e:
        logger.warning(f"Could not message user {user_id}: {e}")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ User must message @CampusDeptGuideBot first.")
    except Exception as e:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Error: {e}")

def main():
    if not TELEGRAM_TOKEN:
        logger.critical("Missing TELEGRAM_BOT_TOKEN")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))
    logger.info("Bot started with robust OpenRouter handling.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
