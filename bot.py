"""
Stormline Management Bot — Telegram bot for managing Stormline Utilities operations.
Handles website updates, project pipeline, email drafts, and general ops Q&A.
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from config import config
from agent import StormlineAgent
from tools import list_projects, list_pending_approvals, process_approval

logger = logging.getLogger(__name__)
agent = StormlineAgent()


# ─── Security ─────────────────────────────────────────────────────────────────

def _is_authorized(update: Update) -> bool:
    return update.effective_chat.id == config.allowed_chat_id


async def _deny(update: Update):
    logger.warning(f"Unauthorized access attempt from chat_id={update.effective_chat.id}")
    await update.effective_message.reply_text("Unauthorized.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def send_long(update: Update, text: str, parse_mode: str = None):
    """Send a message, splitting if over Telegram's 4096-char limit."""
    limit = 4000
    if len(text) <= limit:
        await update.effective_message.reply_text(text, parse_mode=parse_mode)
        return
    chunks = [text[i:i+limit] for i in range(0, len(text), limit)]
    for chunk in chunks:
        await update.effective_message.reply_text(chunk, parse_mode=parse_mode)


# ─── Commands ─────────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    msg = (
        "Stormline Management Bot\n\n"
        "I manage your project pipeline, website, and communications.\n\n"
        "/status — ops overview\n"
        "/projects — bid pipeline\n"
        "/website — website management\n"
        "/approvals — pending approvals\n"
        "/clear — clear conversation history\n"
        "/help — this menu\n\n"
        "Or just talk to me — ask anything about your business."
    )
    await update.message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    msg = (
        "Stormline Bot Commands\n\n"
        "/status — quick ops overview\n"
        "/projects [status] — list projects (filter: estimating, submitted, won, etc.)\n"
        "/email [query] — check Gmail inbox\n"
        "/website — read website sections\n"
        "/approvals — review pending website/email approvals\n"
        "/clear — reset conversation history\n\n"
        "Examples:\n"
        "  'Add a new bid: Rowlett Hotel, GC is Tanner, estimating, $450K'\n"
        "  'Update the website hero text to say...'\n"
        "  'Draft an email to the GC at...'\n"
        "  'What's in my pipeline?'\n"
    )
    await update.message.reply_text(msg)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    await update.message.chat.send_action("typing")
    response = await agent.respond(
        update.effective_user.id,
        "Give me a quick ops status. Check three things and summarize concisely:\n"
        "1. Project pipeline — active bids, anything submitted or estimating\n"
        "2. Gmail inbox — any bid invites, supplier quotes, plan deliveries, or GC messages worth knowing about\n"
        "3. Pending approvals — anything waiting on me\n"
        "Keep it tight. Flag anything urgent."
    )
    await send_long(update, response)


async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    status_filter = ' '.join(context.args) if context.args else None
    data = list_projects(status_filter)
    projects = data['projects']

    if not projects:
        filter_msg = f" with status '{status_filter}'" if status_filter else ""
        await update.message.reply_text(f"No projects found{filter_msg}.")
        return

    lines = [f"Projects ({data['count']}):"]
    for p in projects:
        amt = f"${p['bid_amount']:,.0f}" if p.get('bid_amount') else "—"
        lines.append(f"\n• {p['name']}")
        lines.append(f"  GC: {p.get('gc_name', '—')} | Status: {p['status']} | Bid: {amt}")
        if p.get('notes'):
            lines.append(f"  Notes: {p['notes'][:80]}")

    await send_long(update, "\n".join(lines))


async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    query = ' '.join(context.args) if context.args else ''
    await update.message.chat.send_action("typing")
    prompt = f"Check my Gmail and summarize what's important. Focus on bid invites, supplier quotes, plan deliveries, and GC communications. Skip noise."
    if query:
        prompt = f"Check my Gmail for: {query}. Summarize what you find."
    response = await agent.respond(update.effective_user.id, prompt)
    await send_long(update, response)


async def website_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    await update.message.chat.send_action("typing")
    response = await agent.respond(
        update.effective_user.id,
        "Read the website hero section and services section and summarize what the website currently says. "
        "Then tell me what sections are available to update."
    )
    await send_long(update, response)


async def approvals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    data = list_pending_approvals()
    pending = data['approvals']

    if not pending:
        await update.message.reply_text("No pending approvals.")
        return

    await update.message.reply_text(f"{len(pending)} pending approval(s):")

    for appr in pending:
        text = f"[{appr['id']}] {appr['type']}\n{appr['description'][:300]}"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{appr['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{appr['id']}"),
            ]
        ])
        await update.message.reply_text(text, reply_markup=keyboard)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    agent.clear_history(update.effective_user.id)
    await update.message.reply_text("Conversation history cleared.")


# ─── Approval callbacks ────────────────────────────────────────────────────────

async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update): return await _deny(update)
    query = update.callback_query
    await query.answer()

    data = query.data
    if ':' not in data:
        return

    action, approval_id = data.split(':', 1)
    approved = action == 'approve'

    result = process_approval(approval_id, approved)
    if result['success']:
        status = "Approved and executed" if approved else "Rejected"
        msg = result.get('result', {}).get('message', '')
        await query.edit_message_text(f"{status}: {approval_id}\n{msg}")
    else:
        await query.edit_message_text(f"Error: {result.get('error')}")


# ─── Message handler ──────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    if not user_message:
        return

    if not _is_authorized(update): return await _deny(update)
    logger.info(f"Message from chat_id={update.effective_chat.id} user={update.effective_user.username}")
    await update.message.chat.send_action("typing")

    try:
        response = await agent.respond(update.effective_user.id, user_message)
        await send_long(update, response)
    except Exception as e:
        logger.error(f"Message handler error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")


# ─── Error handler ────────────────────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("An error occurred. Please try again.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("Starting Stormline Management Bot...")

    app = Application.builder().token(config.telegram_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("website", website_command))
    app.add_handler(CommandHandler("approvals", approvals_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(approval_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot running.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
