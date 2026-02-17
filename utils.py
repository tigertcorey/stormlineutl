"""
Utility functions for Stormline UTL Bot.
Provides helper functions for logging, error handling, and message formatting.
"""

import logging
import asyncio
import io
from typing import Optional, Callable, Any, List
from functools import wraps

logger = logging.getLogger(__name__)


def sanitize_input(text: str, max_length: int = 4000) -> str:
    """
    Sanitize user input to prevent injection attacks and limit length.
    
    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized text
    """
    if not text:
        return ""
    
    # Strip whitespace and limit length
    text = text.strip()[:max_length]
    
    # Basic sanitization - remove null bytes
    text = text.replace('\x00', '')
    
    return text


def format_synthesized_response(synthesized: str, claude_resp: str, gpt_resp: str) -> str:
    """
    Format a synthesized response with individual model perspectives.
    
    Args:
        synthesized: Synthesized answer
        claude_resp: Claude's response
        gpt_resp: GPT-4's response
        
    Returns:
        Formatted response string
    """
    response = f"🤖 **Synthesized Answer:**\n{synthesized}\n\n"
    response += "---\n"
    response += f"💡 **Claude's perspective:**\n{claude_resp}\n\n"
    response += f"🧠 **GPT-4's perspective:**\n{gpt_resp}"
    
    return response


def format_error_message(error: Exception, user_friendly: bool = True) -> str:
    """
    Format error message for user display.
    
    Args:
        error: Exception object
        user_friendly: Whether to show user-friendly message
        
    Returns:
        Formatted error message
    """
    if user_friendly:
        return "⚠️ I encountered an issue processing your request. Please try again later."
    else:
        return f"Error: {str(error)}"


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator for retrying async functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {delay}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries} attempts failed for {func.__name__}: {str(e)}"
                        )
            
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


class ConversationHistory:
    """Manages conversation history for users."""
    
    def __init__(self, max_length: int = 10):
        """
        Initialize conversation history manager.
        
        Args:
            max_length: Maximum number of messages to keep per user
        """
        self.histories = {}
        self.max_length = max_length
    
    def add_message(self, user_id: int, role: str, content: str):
        """
        Add a message to user's conversation history.
        
        Args:
            user_id: Telegram user ID
            role: Message role ('user' or 'assistant')
            content: Message content
        """
        if user_id not in self.histories:
            self.histories[user_id] = []
        
        self.histories[user_id].append({
            'role': role,
            'content': content
        })
        
        # Trim history if it exceeds max length
        if len(self.histories[user_id]) > self.max_length * 2:  # *2 for user+assistant pairs
            self.histories[user_id] = self.histories[user_id][-self.max_length * 2:]
    
    def get_history(self, user_id: int) -> list:
        """
        Get conversation history for a user.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            List of message dictionaries
        """
        return self.histories.get(user_id, [])
    
    def clear_history(self, user_id: int):
        """
        Clear conversation history for a user.
        
        Args:
            user_id: Telegram user ID
        """
        if user_id in self.histories:
            self.histories[user_id] = []


def truncate_text(text: str, max_length: int = 4000, suffix: str = "...") -> str:
    """
    Truncate text to maximum length with suffix.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def pdf_to_images(pdf_bytes: bytes, max_pages: int = 10) -> List[bytes]:
    """
    Convert PDF pages to images.
    
    Args:
        pdf_bytes: PDF file bytes
        max_pages: Maximum pages to convert
        
    Returns:
        List of image bytes (one per page)
        
    Raises:
        Exception: If PDF conversion fails
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image
        
        images = []
        
        # Open PDF from bytes
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Limit to max_pages
        num_pages = min(len(pdf_document), max_pages)
        
        logger.info(f"Converting {num_pages} pages from PDF to images")
        
        for page_num in range(num_pages):
            # Get page
            page = pdf_document[page_num]
            
            # Render page to image (matrix scales the image)
            # Use 2.0 zoom for good quality
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Save to bytes
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            images.append(img_bytes.getvalue())
            
            logger.debug(f"Converted page {page_num + 1}/{num_pages}")
        
        pdf_document.close()
        
        logger.info(f"Successfully converted {len(images)} PDF pages to images")
        return images
        
    except ImportError as e:
        logger.error(f"Required library not found for PDF processing: {e}")
        raise Exception("PDF processing libraries not available")
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}")
        raise Exception(f"Failed to process PDF: {str(e)}")
