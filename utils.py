"""
Utility functions for Stormline UTL Bot.
Provides helper functions for logging, error handling, and message formatting.
"""

import logging
import asyncio
from typing import Optional, Callable, Any
from functools import wraps
import tempfile
import os
from pypdf import PdfReader

logger = logging.getLogger(__name__)


class PDFProcessingError(Exception):
    """Custom exception for PDF processing errors."""
    pass


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


async def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text content from a PDF file.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Extracted text content
        
    Raises:
        PDFProcessingError: If PDF extraction fails
    """
    try:
        logger.info(f"Extracting text from PDF: {file_path}")
        
        # Run PDF extraction in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            _extract_pdf_sync,
            file_path
        )
        
        logger.info(f"Successfully extracted {len(text)} characters from PDF")
        return text
        
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        raise PDFProcessingError(f"Failed to process PDF: {str(e)}") from e



def _extract_pdf_sync(file_path: str) -> str:
    """
    Synchronous PDF text extraction (to be run in thread pool).
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Extracted text content
    """
    reader = PdfReader(file_path)
    text_parts = []
    
    for page_num, page in enumerate(reader.pages, 1):
        try:
            page_text = page.extract_text()
            if page_text.strip():
                text_parts.append(f"--- Page {page_num} ---\n{page_text}\n")
        except Exception as e:
            logger.warning(f"Failed to extract text from page {page_num}: {e}")
            text_parts.append(f"--- Page {page_num} ---\n[Could not extract text from this page]\n")
    
    if not text_parts:
        raise PDFProcessingError("No text could be extracted from the PDF")
    
    return "\n".join(text_parts)
