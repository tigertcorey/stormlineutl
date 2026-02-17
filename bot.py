"""
Stormline UTL Bot - Multi-AI Telegram Bot
Main bot entry point with command handlers and message processing.
"""

import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from config import config
from ai_models import MultiModelOrchestrator
from utils import (
    sanitize_input,
    format_synthesized_response,
    format_error_message,
    ConversationHistory
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize components
orchestrator = MultiModelOrchestrator()
conversation_history = ConversationHistory(max_length=config.max_history_length)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /start command.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot")
    
    # Escape special characters in user's first name for Markdown
    safe_first_name = user.first_name.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
    
    welcome_message = f"""👋 Welcome to **Stormline UTL Bot**, {safe_first_name}!

I'm a multi-AI assistant powered by Claude 3.5 Sonnet and GPT-4. I can help you with questions, analysis, coding, writing, and more!

**Available Commands:**
/start - Show this welcome message
/help - Get detailed help and usage examples
/claude <message> - Query Claude AI only
/gpt <message> - Query GPT-4 only
/both <message> - Query both AIs and get a synthesized response

**Default Behavior:**
Just send me any message, and I'll automatically query both AI models and provide you with a comprehensive synthesized answer along with individual perspectives!

**Example:**
`Explain quantum computing in simple terms`

Let's get started! 🚀"""
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /help command.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    logger.info(f"User {user.id} requested help")
    
    help_message = """📚 **Stormline UTL Bot - Help Guide**

**Commands:**

🔹 `/start` - Welcome message and quick introduction

🔹 `/help` - Show this help guide

🔹 `/claude <message>` - Query only Claude AI
   Example: `/claude What are the benefits of async programming?`

🔹 `/gpt <message>` - Query only GPT-4
   Example: `/gpt Explain machine learning concepts`

🔹 `/both <message>` - Query both models and get synthesized response
   Example: `/both What is the future of AI?`

**Default Behavior:**
Send any message without a command, and I'll automatically use `/both` mode to give you the best possible answer!

**Features:**
✅ Conversation history tracking (last 10 messages)
✅ Multi-model consensus for better answers
✅ Graceful fallback if one model is unavailable
✅ Smart error handling and retry logic

**Response Format (Both Mode):**
When using both models, you'll receive:
- 🤖 Synthesized answer combining best insights
- 💡 Claude's unique perspective
- 🧠 GPT-4's unique perspective

**Tips:**
- Be specific in your questions for best results
- Use `/claude` or `/gpt` if you prefer a specific model's style
- Conversation history helps with follow-up questions

Need more help? Just ask! 💬"""
    
    await update.message.reply_text(help_message, parse_mode='Markdown')


async def claude_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /claude command - Query only Claude.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    user_message = ' '.join(context.args) if context.args else ''
    
    if not user_message:
        await update.message.reply_text(
            "Please provide a message after the command.\n"
            "Example: `/claude Explain async programming`",
            parse_mode='Markdown'
        )
        return
    
    logger.info(f"User {user.id} querying Claude: {user_message[:50]}...")
    
    # Send typing indicator
    await update.message.chat.send_action(action="typing")
    
    try:
        # Sanitize input
        user_message = sanitize_input(user_message, config.max_message_length)
        
        # Get conversation history
        history = conversation_history.get_history(user.id)
        
        # Query Claude
        response = await orchestrator.query_claude(user_message, history)
        
        # Store in conversation history
        conversation_history.add_message(user.id, 'user', user_message)
        conversation_history.add_message(user.id, 'assistant', response)
        
        # Send response
        await update.message.reply_text(f"💡 **Claude:**\n\n{response}", parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in claude_command: {e}")
        await update.message.reply_text(format_error_message(e))


async def gpt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /gpt command - Query only GPT-4.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    user_message = ' '.join(context.args) if context.args else ''
    
    if not user_message:
        await update.message.reply_text(
            "Please provide a message after the command.\n"
            "Example: `/gpt What is machine learning?`",
            parse_mode='Markdown'
        )
        return
    
    logger.info(f"User {user.id} querying GPT-4: {user_message[:50]}...")
    
    # Send typing indicator
    await update.message.chat.send_action(action="typing")
    
    try:
        # Sanitize input
        user_message = sanitize_input(user_message, config.max_message_length)
        
        # Get conversation history
        history = conversation_history.get_history(user.id)
        
        # Query GPT-4
        response = await orchestrator.query_gpt(user_message, history)
        
        # Store in conversation history
        conversation_history.add_message(user.id, 'user', user_message)
        conversation_history.add_message(user.id, 'assistant', response)
        
        # Send response
        await update.message.reply_text(f"🧠 **GPT-4:**\n\n{response}", parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in gpt_command: {e}")
        await update.message.reply_text(format_error_message(e))


async def both_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /both command - Query both models and synthesize.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    user_message = ' '.join(context.args) if context.args else ''
    
    if not user_message:
        await update.message.reply_text(
            "Please provide a message after the command.\n"
            "Example: `/both What is the future of AI?`",
            parse_mode='Markdown'
        )
        return
    
    logger.info(f"User {user.id} querying both models: {user_message[:50]}...")
    
    # Send typing indicator
    await update.message.chat.send_action(action="typing")
    
    try:
        # Sanitize input
        user_message = sanitize_input(user_message, config.max_message_length)
        
        # Get conversation history
        history = conversation_history.get_history(user.id)
        
        # Query both models
        synthesized, claude_resp, gpt_resp = await orchestrator.query_both(
            user_message, history
        )
        
        # Store in conversation history
        conversation_history.add_message(user.id, 'user', user_message)
        conversation_history.add_message(user.id, 'assistant', synthesized)
        
        # Format and send response
        response = format_synthesized_response(synthesized, claude_resp, gpt_resp)
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in both_command: {e}")
        await update.message.reply_text(format_error_message(e))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle regular messages (default: query both models).
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    user_message = update.message.text
    
    if not user_message:
        return
    
    logger.info(f"User {user.id} sent message: {user_message[:50]}...")
    
    # Send typing indicator
    await update.message.chat.send_action(action="typing")
    
    try:
        # Sanitize input
        user_message = sanitize_input(user_message, config.max_message_length)
        
        # Get conversation history
        history = conversation_history.get_history(user.id)
        
        # Query both models (default behavior)
        synthesized, claude_resp, gpt_resp = await orchestrator.query_both(
            user_message, history
        )
        
        # Store in conversation history
        conversation_history.add_message(user.id, 'user', user_message)
        conversation_history.add_message(user.id, 'assistant', synthesized)
        
        # Format and send response
        response = format_synthesized_response(synthesized, claude_resp, gpt_resp)
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text(format_error_message(e))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle errors in the bot.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An unexpected error occurred. Please try again later."
        )


def main():
    """Main function to run the bot."""
    # Validate configuration
    if not config.validate():
        logger.error("Configuration validation failed. Exiting.")
        return
    
    logger.info("Starting Stormline UTL Bot...")
    
    # Create application
    application = Application.builder().token(config.telegram_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("claude", claude_command))
    application.add_handler(CommandHandler("gpt", gpt_command))
    application.add_handler(CommandHandler("both", both_command))
    
    # Add message handler for regular messages
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
