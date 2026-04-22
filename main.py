#!/usr/bin/env python3
"""
Campus Department Guide Bot - FINAL VERSION
- Invite links sent to admin
- Bot works in DM only
- Free = general, Paid = detailed
"""

import os
import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Tuple

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

ADMIN_USER_ID = 8228561129

# OpenRouter settings
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PRIMARY_MODEL = "deepseek/deepseek-r1"
FALLBACK_MODEL = "google/gemini-2.0-flash-exp"

# Payment details
TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# System Prompt - Strict Free vs Paid
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are **Campus Guide**, an AI assistant for Ethiopian university students.

**FREE USERS (not in paid group):**
- Give ONLY general overviews of departments
- NO salary numbers, NO AI risk scores, NO detailed job outlooks
- Encourage payment of {PRICE} for full access
- Template: "Here's a general overview of [Department]. For detailed salary information and career outlooks, unlock full access for {PRICE}. Pay via Telebirr {TELEBIRR_NUMBER} ({TELEBIRR_NAME}) or CBE {CBE_ACCOUNT} ({CBE_NAME})."

**PAID USERS (in paid group):**
- Provide specific salary ranges in ETB
- Give AI risk assessments
- Share detailed job outlooks and employer information
- Provide Masters pathways

**Payment:** {PRICE} via Telebirr {TELEBIRR_NUMBER} ({TELEBIRR_NAME}) or CBE {CBE_ACCOUNT} ({CBE_NAME})
**Support:** {SUPPORT_USERNAME}

Keep responses under 200 words. Be specific to Ethiopian context."""

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
        logger.error(f"Group check error: {e}")
        return False

# -----------------------------------------------------------------------------
# AI: Call OpenRouter
# -----------------------------------------------------------------------------
async def call_openrouter(prompt: str, use_fallback: bool = False) -> Tuple[Optional[str], Optional[str]]:
    model = FALLBACK_MODEL if use_fallback else PRIMARY_MODEL
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
        "max_tokens": 500
    }

    attempt = 0
    max_retries = 3
    base_delay = 5

    while attempt < max_retries:
        attempt += 1
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT) as resp:
                    data = await resp.json()

                    if "choices" in data:
                        return data["choices"][0]["message"]["content"], None

                    error = data.get("error", {})
                    error_msg = error.get("message", "Unknown error")

                    if "No endpoints found" in error_msg and not use_fallback:
                        logger.warning(f"Routing error. Switching to fallback...")
                        return await call_openrouter(prompt, use_fallback=True)

                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                        await asyncio.sleep(delay)
                        continue

                    return None, error_msg

        except asyncio.TimeoutError:
            if attempt < max_retries:
                await asyncio.sleep(base_delay * attempt)
                continue
            return None, "Request timed out."
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(base_delay * attempt)
                continue
            return None, str(e)

    return None, "Max retries exceeded."

async def get_ai_response(user_message: str, is_paid: bool) -> str:
    prompt = SYSTEM_PROMPT
    
    if is_paid:
        prompt += "\n\nThis user IS a paid member. Provide detailed answers with specific salary ranges in ETB, AI risk scores, and complete career outlooks."
    else:
        prompt += f"\n\nThis user is NOT paid. Provide ONLY general overviews. NO salary numbers. Encourage {PRICE} payment."
    
    prompt += f"\n\nStudent: {user_message}\nCampus Guide:"

    response, error = await call_openrouter(prompt)
    if response:
        return response
    return f"⚠️ Service unavailable. Reason: {error}"

# -----------------------------------------------------------------------------
# Start Command
# -----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        f"🎓 Welcome to Campus Department Guide!\n\n"
        f"I help Ethiopian students choose the right university department.\n\n"
        f"💰 Full Access: {PRICE} one-time\n\n"
        f"Payment Methods:\n"
        f"- Telebirr: {TELEBIRR_NUMBER} ({TELEBIRR_NAME})\n"
        f"- CBE: {CBE_ACCOUNT} ({CBE_NAME})\n\n"
        f"📸 Send payment screenshot to unlock detailed information.\n\n"
        f"Support: {SUPPORT_USERNAME}"
    )
    await update.message.reply_text(welcome)

# -----------------------------------------------------------------------------
# Message Handler (DM Only)
# -----------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text.strip()
    
    # Only respond to private messages
    if update.effective_chat.type != "private":
        return
    
    logger.info(f"Message from @{user.username or user_id}: {user_message[:100]}")

    is_paid = await is_user_in_paid_group(user_id, context)
    await update.message.chat.send_action(action="typing")
    ai_response = await get_ai_response(user_message, is_paid)
    await update.message.reply_text(ai_response)

# -----------------------------------------------------------------------------
# Payment Handlers (DM Only)
# -----------------------------------------------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only respond to private messages
    if update.effective_chat.type != "private":
        return
    
    user = update.effective_user
    photo = update.message.photo[-1]
    
    keyboard = [[InlineKeyboardButton(f"✅ Approve @{user.username or user.id}", callback_data=f"approve_{user.id}")]]
    
    await context.bot.send_photo(
        chat_id=ADMIN_USER_ID,
        photo=photo.file_id,
        caption=f"Payment from @{user.username or user.id} (ID: {user.id})",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✅ Received! You'll get access shortly.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only respond to private messages
    if update.effective_chat.type != "private":
        return
    
    user = update.effective_user
    doc = update.message.document
    
    keyboard = [[InlineKeyboardButton(f"✅ Approve @{user.username or user.id}", callback_data=f"approve_{user.id}")]]
    
    await context.bot.send_document(
        chat_id=ADMIN_USER_ID,
        document=doc.file_id,
        caption=f"Payment document from @{user.username or user.id} (ID: {user.id})",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✅ Received! You'll get access shortly.")

# -----------------------------------------------------------------------------
# Approval Callback - Sends Link to Admin (100% Reliable)
# -----------------------------------------------------------------------------
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        user_id = int(query.data.split('_')[1])
    except (ValueError, IndexError):
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Invalid user ID.")
        return

    # Create invite link
    try:
        link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID,
            member_limit=1
        )
        
        # ALWAYS send link to ADMIN
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                f"✅ APPROVED - User ID: {user_id}\n\n"
                f"📋 Send this invite link to the user:\n{link.invite_link}\n\n"
                f"⚠️ Remind them to click @CampusDeptGuideBot and press START."
            )
        )
        
        # Optional: Try to notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ Your payment has been approved!\n\n"
                    f"The admin will send your invite link shortly.\n\n"
                    f"Support: {SUPPORT_USERNAME}"
                )
            )
        except:
            pass
        
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ Approved! Link sent to you.")
        
    except Exception as e:
        logger.error(f"Approval error: {e}")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Error: {e}")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.critical("Missing TELEGRAM_BOT_TOKEN")
        return
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))
    
    # Clear webhook before polling
    print("Clearing webhook...")
    app.bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("Bot started - DM only, free=general, paid=detailed.")
    app.run_polling()

if __name__ == "__main__":
    main()
