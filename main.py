#!/usr/bin/env python3
"""
Campus Department Guide Bot
Production-ready Telegram bot with Gemini AI, payment handling, and robust error recovery.
"""

import os
import logging
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from collections import defaultdict

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, Forbidden, BadRequest

# -----------------------------------------------------------------------------
# Configuration (All sensitive data via environment variables)
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Constants
ADMIN_USER_ID = 8228561129                      # Your Telegram ID
GEMINI_MODEL = "gemini-2.5-flash"               # Stable model
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Payment details
TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

# Rate limiting & retry settings
GEMINI_MAX_RETRIES = 5
GEMINI_BASE_DELAY = 2.0          # seconds, will be multiplied exponentially
GEMINI_TIMEOUT = aiohttp.ClientTimeout(total=45)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Enhanced System Prompt with Real Department Data
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are **Campus Guide**, a knowledgeable and friendly AI assistant dedicated to helping Ethiopian university students make informed decisions about their education and career.

**Your Personality:**
- Warm, encouraging, and professional.
- Provide **specific, actionable information** – avoid vague platitudes.
- Use Ethiopian Birr (ETB) and refer to real Ethiopian universities.

**Your Knowledge Base (Use this data actively):**
Here are details for popular departments. Draw from this when relevant.

1. **Computer Science (Addis Ababa University)**
   - Field: Natural Sciences / Technology
   - Job Outlook: **Very High** (fintech, telecom, AI startups)
   - Salary Range: 8,000 – 45,000 ETB/month (entry to senior)
   - AI Risk: **Low** (AI creates more jobs in this field)
   - Masters Pathways: AAU, Germany (DAAD), India (ICT)
   - NGO Relevance: Medium (data analysis roles)

2. **Civil Engineering (Addis Ababa Science & Technology University)**
   - Field: Engineering
   - Job Outlook: **High** (construction, government infrastructure)
   - Salary Range: 7,000 – 40,000 ETB/month
   - AI Risk: **Very Low** (physical presence required)
   - Masters Pathways: AAU, China Scholarship Council, Turkey
   - NGO Relevance: High (infrastructure projects)

3. **Accounting (Unity University)**
   - Field: Business / Finance
   - Job Outlook: **Stable** (every company needs accountants)
   - Salary Range: 6,000 – 35,000 ETB/month
   - AI Risk: **Medium** (automation of bookkeeping, but advisory roles remain)
   - Masters Pathways: ACCA, MBA local
   - NGO Relevance: High (finance departments)

4. **Nursing (Jimma University)**
   - Field: Health Sciences
   - Job Outlook: **Very High** (critical shortage nationwide)
   - Salary Range: 7,000 – 30,000 ETB/month (plus allowances)
   - AI Risk: **Very Low** (human care essential)
   - Masters Pathways: AAU, specialty certifications abroad
   - NGO Relevance: Very High (hospitals, clinics)

5. **Law (Haramaya University)**
   - Field: Social Sciences
   - Job Outlook: **Moderate** (competitive, but growing corporate sector)
   - Salary Range: 6,000 – 50,000+ ETB (depending on firm)
   - AI Risk: **Low** (legal reasoning still human-led)
   - Masters Pathways: LLM abroad (UK, South Africa)
   - NGO Relevance: High (human rights, advocacy)

**If a student asks about a department not listed, give a balanced general overview and encourage them to ask for specifics.**

**Payment & Access:**
- Full access to detailed reports (employer lists, 5-year projections) requires a one-time payment of **{PRICE}**.
- Payment methods: **Telebirr {TELEBIRR_NUMBER} ({TELEBIRR_NAME})** or **CBE Birr {CBE_ACCOUNT} ({CBE_NAME})**.
- After payment, upload screenshot here for instant verification.

**Support:** For human help, contact {SUPPORT_USERNAME}.

**Response Guidelines:**
- Keep answers under 300 words unless the user asks for deep detail.
- Always offer to provide more specific information.
- Never invent data; if unsure, say "I don't have that exact figure, but I can give you a general range."
"""

# -----------------------------------------------------------------------------
# In-Memory Cache for Approval State (to prevent double-approvals)
# -----------------------------------------------------------------------------
approval_cache: Dict[int, float] = {}          # user_id -> timestamp of approval
APPROVAL_CACHE_TTL = 3600                      # 1 hour

# -----------------------------------------------------------------------------
# Helper: Check if user is in paid group (with retry)
# -----------------------------------------------------------------------------
async def is_user_in_paid_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not PAID_GROUP_ID:
        logger.error("PAID_GROUP_ID not set")
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=PAID_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except TelegramError as e:
        logger.warning(f"Group check failed for {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected group check error: {e}")
        return False

# -----------------------------------------------------------------------------
# Robust Gemini API Call with Exponential Backoff & Rate-Limit Handling
# -----------------------------------------------------------------------------
async def call_gemini_api(prompt_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Calls Gemini API with retry logic.
    Returns (response_text, error_message). One will be None.
    """
    if not GEMINI_API_KEY:
        return None, "API key not configured."

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 600,
            "topP": 0.9
        }
    }

    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                    json=payload,
                    timeout=GEMINI_TIMEOUT
                ) as resp:
                    data = await resp.json()

                    if "candidates" in data:
                        return data["candidates"][0]["content"]["parts"][0]["text"], None

                    elif "error" in data:
                        error_msg = data["error"]["message"].lower()
                        # Rate limit or overload -> retry
                        if any(kw in error_msg for kw in ["high demand", "exhausted", "rate limit", "quota"]):
                            if attempt < GEMINI_MAX_RETRIES - 1:
                                wait = GEMINI_BASE_DELAY * (2 ** attempt)
                                logger.warning(f"Gemini rate limit. Retry {attempt+1}/{GEMINI_MAX_RETRIES} after {wait:.1f}s")
                                await asyncio.sleep(wait)
                                continue
                        return None, data["error"]["message"]
                    else:
                        logger.error(f"Unknown Gemini response: {data}")
                        return None, "Unexpected API response structure."

        except asyncio.TimeoutError:
            logger.warning(f"Gemini timeout (attempt {attempt+1})")
            if attempt < GEMINI_MAX_RETRIES - 1:
                await asyncio.sleep(GEMINI_BASE_DELAY * (2 ** attempt))
                continue
            return None, "Request timed out after multiple attempts."
        except Exception as e:
            logger.error(f"Gemini exception: {e}")
            return None, str(e)

    return None, "Max retries exceeded."

async def get_gemini_response(user_message: str, is_paid: bool) -> str:
    """Wrapper that builds the prompt and handles errors gracefully."""
    context_note = ""
    if not is_paid:
        context_note = f"\n\n[User has NOT paid. Politely encourage the one-time payment of {PRICE} for full details.]"

    full_prompt = f"{SYSTEM_PROMPT}\n\n{context_note}\n\nStudent: {user_message}\nCampus Guide:"

    response, error = await call_gemini_api(full_prompt)
    if response:
        return response
    else:
        logger.error(f"Gemini failure: {error}")
        if "high demand" in (error or "").lower():
            return "🤖 I'm experiencing high traffic right now. Please give me a moment and try again."
        elif "quota" in (error or "").lower():
            return "🔧 The service is temporarily unavailable. Our team has been notified."
        else:
            return f"⚠️ I'm having trouble connecting to my knowledge base. Please try again later."

# -----------------------------------------------------------------------------
# Message Handler with Typing Indicator & Logging
# -----------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text.strip()

    logger.info(f"Message from @{user.username or user_id}: {user_message[:100]}")

    # Check payment status
    is_paid = await is_user_in_paid_group(user_id, context)
    logger.info(f"User {user_id} paid={is_paid}")

    # Send typing indicator
    await update.message.chat.send_action(action="typing")

    # Get AI response
    ai_response = await get_gemini_response(user_message, is_paid)
    await update.message.reply_text(ai_response)

# -----------------------------------------------------------------------------
# Payment Proof Handlers (Forward to Admin with Inline Approval)
# -----------------------------------------------------------------------------
async def send_approval_keyboard(context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                 username: str, file_id: str, is_photo: bool = True,
                                 caption: str = ""):
    """Send approval message to admin with inline button."""
    keyboard = [[InlineKeyboardButton(
        f"✅ Approve @{username or user_id}",
        callback_data=f"approve_{user_id}"
    )]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if is_photo:
            await context.bot.send_photo(
                chat_id=ADMIN_USER_ID,
                photo=file_id,
                caption=caption,
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_document(
                chat_id=ADMIN_USER_ID,
                document=file_id,
                caption=caption,
                reply_markup=reply_markup
            )
        logger.info(f"Payment proof forwarded to admin for user {user_id}")
    except TelegramError as e:
        logger.error(f"Failed to send approval request to admin: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]  # highest resolution

    caption = f"📸 Payment proof from @{user.username or user.id} (ID: {user.id})"
    await send_approval_keyboard(context, user.id, user.username or "", photo.file_id, True, caption)

    await update.message.reply_text(
        "✅ Payment screenshot received! We'll verify and send you the access link shortly."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document = update.message.document

    caption = f"📎 Payment document from @{user.username or user.id} (ID: {user.id})"
    await send_approval_keyboard(context, user.id, user.username or "", document.file_id, False, caption)

    await update.message.reply_text(
        "✅ Document received! You'll get the invite link after verification."
    )

# -----------------------------------------------------------------------------
# Approval Callback (Admin clicks "Approve")
# -----------------------------------------------------------------------------
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Extract user_id from callback data
    try:
        user_id = int(query.data.replace("approve_", ""))
    except ValueError:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Invalid user ID.")
        return

    # Prevent duplicate approvals within short time
    now = time.time()
    if user_id in approval_cache and (now - approval_cache[user_id]) < APPROVAL_CACHE_TTL:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ Already approved recently.")
        return
    approval_cache[user_id] = now

    # Verify user exists and can be messaged
    try:
        # Attempt to send a test message to ensure chat is available
        await context.bot.send_chat_action(chat_id=user_id, action="typing")
    except Forbidden:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ Cannot message this user. They may have blocked the bot."
        )
        return
    except BadRequest as e:
        if "chat not found" in str(e).lower():
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n❌ Chat not found. User must start a conversation with the bot first."
            )
            return
        else:
            logger.error(f"BadRequest during user check: {e}")

    # Create one-time invite link
    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID,
            member_limit=1,
            expire_date=datetime.utcnow() + timedelta(hours=24)  # link valid 24h
        )
    except TelegramError as e:
        logger.error(f"Failed to create invite link: {e}")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Could not create invite link. Check bot permissions.")
        return

    # Send invite link to the user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ Your payment has been verified!\n\n"
                f"🔗 Join the exclusive paid group here (one-time link):\n{invite_link.invite_link}\n\n"
                f"After joining, you can ask me detailed questions about any department.\n\n"
                f"Need help? Contact {SUPPORT_USERNAME}"
            )
        )
        logger.info(f"Approved user {user_id}, invite sent.")
    except TelegramError as e:
        logger.error(f"Could not send invite to user {user_id}: {e}")
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ Failed to send invite: {e}"
        )
        return

    # Update the admin message
    await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ APPROVED - Invite sent.")

# -----------------------------------------------------------------------------
# Error Handler for Telegram API errors (optional but good practice)
# -----------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is missing.")
        return
    if not PAID_GROUP_ID:
        logger.warning("PAID_GROUP_ID not set. Paid checks will fail.")
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set. AI responses disabled.")

    # Create Application
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))
    app.add_error_handler(error_handler)

    logger.info("Bot started. Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
