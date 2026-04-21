#!/usr/bin/env python3
"""
Campus Department Guide Bot with RAG
Uses OpenRouter AI + Supabase Vector Database for PDF search
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
from supabase import create_client, Client

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PAID_GROUP_ID = os.environ.get("PAID_GROUP_ID")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Admin Telegram ID
ADMIN_USER_ID = 8228561129

# OpenRouter settings
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
MODEL =  "deepseek/deepseek-r1:free"
FALLBACK_MODEL = "deepseek/deepseek-r1:free"

# Payment details
TELEBIRR_NUMBER = "0932223736"
TELEBIRR_NAME = "Banch"
CBE_ACCOUNT = "1000748634456"
CBE_NAME = "Banch"
PRICE = "70 ETB"
SUPPORT_USERNAME = "@Enha127"

# Retry settings
MAX_RETRIES = 3
BASE_DELAY = 2.0
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=45)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# -----------------------------------------------------------------------------
# System Prompt
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are **Campus Guide**, an AI assistant dedicated exclusively to helping Ethiopian university students choose the right department and career path.

**YOUR STRICT RULES:**
1. ONLY answer questions about Ethiopian university departments and careers.
2. If asked about ANY other topic, respond ONLY with:
   "I'm sorry, but my purpose is strictly to help Ethiopian students with university department and career guidance."
3. Never invent data. Use provided context or give general overviews.

**FREE vs PAID:**
- Free users: General overviews, encourage payment of {PRICE}
- Paid users: Detailed answers from uploaded department documents

Payment: Telebirr {TELEBIRR_NUMBER} ({TELEBIRR_NAME}) or CBE {CBE_ACCOUNT} ({CBE_NAME})
Support: {SUPPORT_USERNAME}
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
    except:
        return False

# -----------------------------------------------------------------------------
# RAG Functions
# -----------------------------------------------------------------------------
async def get_embedding(text: str) -> Optional[list]:
    """Get embedding vector for text via OpenRouter."""
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openai/text-embedding-3-small",
            "input": [text]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(EMBEDDINGS_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT) as resp:
                data = await resp.json()
                return data["data"][0]["embedding"]
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None

def search_documents(query_embedding: list, match_count: int = 3) -> list:
    """Search Supabase for similar document chunks."""
    if not supabase:
        return []
    try:
        result = supabase.rpc(
            "match_documents",
            {"query_embedding": query_embedding, "match_count": match_count}
        ).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

# -----------------------------------------------------------------------------
# AI Response
# -----------------------------------------------------------------------------
async def call_openrouter(prompt: str, use_fallback: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Call OpenRouter chat API."""
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

    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT) as resp:
                    data = await resp.json() logger.info(f"OpenRouter response: {data}")
                    if "choices" in data:
                        return data["choices"][0]["message"]["content"], None
                    elif "error" in data:
                        err = data["error"].get("message", "").lower()
                        if any(kw in err for kw in ["rate", "limit", "overloaded"]):
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                                continue
                        return None, data["error"].get("message", "API error")
        except asyncio.TimeoutError:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                continue
            return None, "Timeout"
        except Exception as e:
            return None, str(e)
    return None, "Max retries exceeded"

async def get_ai_response(user_message: str, is_paid: bool) -> str:
    """Get AI response with RAG for paid users."""
    context_note = ""
    if not is_paid:
        context_note = f"\n\n[User has NOT paid. Encourage payment of {PRICE} for full details.]"
        full_prompt = f"{SYSTEM_PROMPT}\n\n{context_note}\n\nStudent: {user_message}\nCampus Guide:"
        response, _ = await call_openrouter(full_prompt)
        return response if response else "⚠️ Service unavailable. Try again later."

    # Paid user - try RAG
    if supabase:
        embedding = await get_embedding(user_message)
        if embedding:
            docs = search_documents(embedding, match_count=3)
            if docs:
                context = "\n\n---\n\n".join([d["content"][:800] for d in docs])
                rag_prompt = f"""{SYSTEM_PROMPT}

Use this context from Ethiopian department documents to answer:
{context}

Student: {user_message}
Campus Guide (use context):"""
                response, _ = await call_openrouter(rag_prompt)
                if response:
                    return response

    # Fallback to regular AI
    full_prompt = f"{SYSTEM_PROMPT}\n\nStudent: {user_message}\nCampus Guide:"
    response, _ = await call_openrouter(full_prompt)
    return response if response else "⚠️ Service unavailable. Try again later."

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
# Payment Handlers
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
# Approval Callback
# -----------------------------------------------------------------------------
approval_cache = {}

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        user_id = int(query.data.replace("approve_", ""))
    except ValueError:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Invalid user ID.")
        return

    now = time.time()
    if user_id in approval_cache and (now - approval_cache[user_id]) < 3600:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ Already approved recently.")
        return
    approval_cache[user_id] = now

    try:
        await context.bot.send_chat_action(chat_id=user_id, action="typing")
    except Forbidden:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ User blocked the bot.")
        return
    except BadRequest as e:
        if "chat not found" in str(e).lower():
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ User must start chat with bot first.")
            return

    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=PAID_GROUP_ID, member_limit=1, expire_date=datetime.utcnow() + timedelta(hours=24)
        )
    except TelegramError as e:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Could not create invite link. Check bot permissions.")
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Payment verified!\n\n🔗 Join the paid group:\n{invite_link.invite_link}\n\nAfter joining, ask me anything!\n\nSupport: {SUPPORT_USERNAME}"
        )
    except TelegramError as e:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Failed to send invite: {e}")
        return

    await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ APPROVED - Invite sent.")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN missing")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))

    logger.info("Bot started with RAG (Supabase + OpenRouter)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
