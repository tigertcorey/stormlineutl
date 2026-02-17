"""
Stormline UTL Bot - Multi-AI Telegram Bot
Main bot entry point with command handlers and message processing.
"""

import logging
import asyncio
import os
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
    ConversationHistory,
    pdf_to_images
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
/analyze - Learn how to upload construction plans and documents

**Default Behavior:**
Just send me any message, and I'll automatically query both AI models and provide you with a comprehensive synthesized answer along with individual perspectives!

**Document Analysis:**
Upload PDFs or images (construction plans, civil drawings) and I'll analyze them using Claude's vision capabilities!

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

🔹 `/analyze` - Instructions for document analysis

**Default Behavior:**
Send any message without a command, and I'll automatically use `/both` mode to give you the best possible answer!

**Document Analysis:**
📄 Upload construction plans, civil drawings, or images for AI-powered analysis!
- Supported formats: PDF, PNG, JPG, JPEG
- Max file size: 20MB
- Send with a caption or prompt for specific analysis
- Example prompts: "Identify all concrete footings", "Calculate linear feet of curb and gutter"

**Features:**
✅ Conversation history tracking (last 10 messages)
✅ Multi-model consensus for better answers
✅ Document and image analysis with Claude Vision
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
- Add captions to documents for targeted analysis

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


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /analyze command - show instructions for document analysis.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    logger.info(f"User {user.id} requested analyze instructions")
    
    analyze_message = """📄 **Document Analysis Guide**

Upload construction plans, civil drawings, or images for AI-powered analysis using Claude's vision capabilities!

**How to Upload:**
1. Click the 📎 attachment icon in Telegram
2. Select a PDF, PNG, JPG, or JPEG file
3. Optionally add a caption with your analysis request
4. Send the document

**Supported Formats:**
✅ PDF files (up to 10 pages converted)
✅ PNG images
✅ JPG/JPEG images
✅ Maximum file size: 20MB

**Example Use Cases:**

📐 **Quantity Takeoff:**
Caption: "Calculate linear feet of curb and gutter"

🏗️ **Site Work Analysis:**
Caption: "Identify all concrete footings and their dimensions"

📊 **Plan Review:**
Caption: "List all items requiring excavation"

🔍 **General Analysis:**
Caption: "Provide a detailed analysis of this construction plan"

**Tips:**
- Be specific in your prompt for best results
- For multi-page PDFs, first 10 pages are analyzed
- You can follow up with questions about uploaded documents
- Upload high-quality images for better accuracy

Ready to analyze? Just upload a document! 📤"""
    
    await update.message.reply_text(analyze_message, parse_mode='Markdown')


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle document and image uploads for plan analysis.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    user = update.effective_user
    
    try:
        # Get the file (could be document or photo)
        file_obj = None
        file_name = None
        is_photo = False
        
        if update.message.document:
            file_obj = update.message.document
            file_name = file_obj.file_name
            logger.info(f"User {user.id} uploaded document: {file_name}")
        elif update.message.photo:
            # Get the largest photo
            file_obj = update.message.photo[-1]
            file_name = f"photo_{file_obj.file_id}.jpg"
            is_photo = True
            logger.info(f"User {user.id} uploaded photo")
        else:
            await update.message.reply_text("⚠️ Please upload a document or photo.")
            return
        
        # Validate file type
        if not is_photo:
            file_ext = os.path.splitext(file_name)[1].lower() if file_name else ''
            supported_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
            if file_ext not in supported_extensions:
                await update.message.reply_text(
                    f"⚠️ Unsupported file format: {file_ext}\n"
                    "Supported formats: PDF, PNG, JPG, JPEG"
                )
                return
        
        # Check file size (20MB limit)
        max_size = 20 * 1024 * 1024  # 20MB
        if file_obj.file_size and file_obj.file_size > max_size:
            await update.message.reply_text(
                f"⚠️ File too large ({file_obj.file_size / 1024 / 1024:.1f}MB). "
                f"Maximum size is 20MB."
            )
            return
        
        # Send processing message
        processing_msg = await update.message.reply_text("🔄 Processing your document...")
        
        # Download the file
        file = await file_obj.get_file()
        file_bytes = await file.download_as_bytearray()
        file_bytes = bytes(file_bytes)
        
        logger.debug(f"Downloaded file: {len(file_bytes)} bytes")
        
        # Get caption/prompt from user
        prompt = update.message.caption if update.message.caption else \
                 "Analyze this construction plan or document in detail. Identify key elements, measurements, and provide a comprehensive analysis."
        
        # Sanitize prompt
        prompt = sanitize_input(prompt, config.max_message_length)
        
        # Get conversation history
        history = conversation_history.get_history(user.id)
        
        # Process based on file type
        if not is_photo and file_name and file_name.lower().endswith('.pdf'):
            # Convert PDF to images
            try:
                images = pdf_to_images(file_bytes, max_pages=10)
                logger.info(f"Converted PDF to {len(images)} images")
                
                # Analyze first page (or all if you want to analyze multiple)
                if images:
                    # For now, analyze just the first page
                    # You could extend this to analyze all pages
                    image_data = images[0]
                    
                    if len(images) > 1:
                        prompt = f"{prompt}\n\n(Note: This is page 1 of {len(images)} pages in the PDF)"
                else:
                    await processing_msg.edit_text("⚠️ Could not extract images from PDF.")
                    return
                    
            except Exception as e:
                logger.error(f"Error processing PDF: {e}")
                await processing_msg.edit_text(f"⚠️ Error processing PDF: {str(e)}")
                return
        else:
            # Direct image upload
            image_data = file_bytes
        
        # Analyze image with Claude Vision
        try:
            response = await orchestrator.claude.analyze_image(
                image_data,
                prompt,
                history
            )
            
            # Store in conversation history
            conversation_history.add_message(user.id, 'user', f"[Uploaded document: {file_name}] {prompt}")
            conversation_history.add_message(user.id, 'assistant', response)
            
            # Send response
            await processing_msg.edit_text(f"🔍 **Document Analysis:**\n\n{response}", parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error analyzing document: {e}")
            await processing_msg.edit_text(f"⚠️ Error analyzing document: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in handle_document: {e}")
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
    application.add_handler(CommandHandler("analyze", analyze_command))
    
    # Add document and photo handler
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO,
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
