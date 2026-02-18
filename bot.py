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
from pdf_processor import PDFProcessor
from takeoff_analyzer import TakeoffAnalyzer

# Configure logging
logger = logging.getLogger(__name__)

# Constants
TELEGRAM_MAX_MESSAGE_LENGTH = 4096  # Maximum characters per Telegram message

# Initialize components
orchestrator = MultiModelOrchestrator()
conversation_history = ConversationHistory(max_length=config.max_history_length)
pdf_processor = PDFProcessor()
takeoff_analyzer = TakeoffAnalyzer()


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
/takeoff - Upload a construction plan PDF for takeoff analysis

**Default Behavior:**
Just send me any message, and I'll automatically query both AI models and provide you with a comprehensive synthesized answer along with individual perspectives!

**Construction Takeoff:**
Upload a PDF of construction plans and use /takeoff to analyze storm, water, sewer, and FDC systems!

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

🔹 `/takeoff` - Upload construction plans (PDF) for takeoff analysis
   1. Upload a PDF file of construction plans
   2. Send /takeoff command
   3. Receive detailed analysis of storm, water, sewer, and FDC systems

**Default Behavior:**
Send any message without a command, and I'll automatically use `/both` mode to give you the best possible answer!

**Features:**
✅ Conversation history tracking (last 10 messages)
✅ Multi-model consensus for better answers
✅ Construction plan takeoff analysis
✅ PDF processing with OCR support
✅ Graceful fallback if one model is unavailable
✅ Smart error handling and retry logic

**Response Format (Both Mode):**
When using both models, you'll receive:
- 🤖 Synthesized answer combining best insights
- 💡 Claude's unique perspective
- 🧠 GPT-4's unique perspective

**Construction Takeoff:**
Upload PDF plans and get automatic quantity takeoff for:
- Storm drainage systems
- Water distribution systems
- Sanitary sewer systems
- Fire Department Connections (FDC)

**Tips:**
- Be specific in your questions for best results
- Use `/claude` or `/gpt` if you prefer a specific model's style
- Conversation history helps with follow-up questions
- For construction takeoffs, ensure PDF plans are clear and readable

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


async def takeoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /takeoff command - Analyze construction plan PDF.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    logger.info(f"User {user.id} requested takeoff analysis")
    
    # Check if user has uploaded a PDF in the message
    message = update.message
    
    # Store the user ID in context for document handler
    if 'awaiting_pdf' not in context.user_data:
        context.user_data['awaiting_pdf'] = {}
    
    context.user_data['awaiting_pdf'][user.id] = True
    
    await update.message.reply_text(
        "📋 **Construction Takeoff Analysis**\n\n"
        "Please upload a PDF file of your construction plans.\n\n"
        "I will analyze the plans and provide a detailed takeoff for:\n"
        "• Storm drainage systems\n"
        "• Water distribution systems\n"
        "• Sanitary sewer systems\n"
        "• Fire Department Connections (FDC)\n\n"
        "Upload your PDF now...",
        parse_mode='Markdown'
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle document uploads (PDF files for takeoff analysis).
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    document = update.message.document
    
    # Check if document is a PDF
    if not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text(
            "⚠️ Please upload a PDF file for takeoff analysis.\n"
            "Use /takeoff command first, then upload your PDF."
        )
        return
    
    logger.info(f"User {user.id} uploaded PDF: {document.file_name}")
    
    # Check if user requested takeoff
    awaiting_pdf = context.user_data.get('awaiting_pdf', {})
    if user.id not in awaiting_pdf or not awaiting_pdf[user.id]:
        await update.message.reply_text(
            "📋 I received a PDF file. Would you like me to analyze it for construction takeoff?\n\n"
            "Use /takeoff command to start the analysis.",
            parse_mode='Markdown'
        )
        return
    
    # Clear the awaiting flag
    context.user_data['awaiting_pdf'][user.id] = False
    
    try:
        # Send processing message
        processing_msg = await update.message.reply_text(
            "⏳ Processing your construction plans...\n"
            "This may take a moment...",
            parse_mode='Markdown'
        )
        
        # Download the file
        file = await document.get_file()
        file_content = await file.download_as_bytearray()
        
        # Save to temporary file
        file_path = pdf_processor.save_uploaded_file(
            bytes(file_content),
            document.file_name
        )
        
        try:
            # Process PDF
            pdf_data = await pdf_processor.process_pdf(file_path)
            pdf_metadata = await pdf_processor.extract_metadata(file_path)
            
            # Update processing message
            await processing_msg.edit_text(
                "📄 PDF processed successfully!\n"
                "🔍 Analyzing construction plans...",
                parse_mode='Markdown'
            )
            
            # Perform takeoff analysis
            analysis = await takeoff_analyzer.analyze_plans(
                pdf_data['text'],
                pdf_metadata,
                systems=['storm', 'water', 'sewer', 'fdc']
            )
            
            # Format and send response
            response = takeoff_analyzer.format_takeoff_response(analysis)
            
            # Delete processing message
            await processing_msg.delete()
            
            # Send analysis results (may need to split if too long)
            if len(response) > TELEGRAM_MAX_MESSAGE_LENGTH:
                # Split into chunks
                chunks = [
                    response[i:i+TELEGRAM_MAX_MESSAGE_LENGTH] 
                    for i in range(0, len(response), TELEGRAM_MAX_MESSAGE_LENGTH)
                ]
                for chunk in chunks:
                    await update.message.reply_text(chunk, parse_mode='Markdown')
            else:
                await update.message.reply_text(response, parse_mode='Markdown')
            
            logger.info(f"Takeoff analysis completed for user {user.id}")
            
        finally:
            # Clean up temporary file
            pdf_processor.cleanup_file(file_path)
        
    except Exception as e:
        logger.error(f"Error processing PDF for takeoff: {e}")
        await update.message.reply_text(
            f"⚠️ Error processing PDF: {str(e)}\n\n"
            "Please ensure your PDF is valid and try again.",
            parse_mode='Markdown'
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
    application.add_handler(CommandHandler("takeoff", takeoff_command))
    
    # Add document handler for PDF uploads
    application.add_handler(MessageHandler(
        filters.Document.MimeType('application/pdf'),
        handle_document
    ))
    
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
