"""
Configuration management for Stormline UTL Bot.
Loads and validates environment variables for bot operation.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)

logger = logging.getLogger(__name__)


class Config:
    """Configuration class for bot settings."""
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        self.telegram_token: str = self._get_required_env('TELEGRAM_BOT_TOKEN')
        self.anthropic_api_key: str = self._get_required_env('ANTHROPIC_API_KEY')
        self.openai_api_key: str = self._get_required_env('OPENAI_API_KEY')
        self.log_level: str = os.getenv('LOG_LEVEL', 'INFO')
        
        # Optional configurations
        self.max_history_length: int = int(os.getenv('MAX_HISTORY_LENGTH', '10'))
        self.max_message_length: int = int(os.getenv('MAX_MESSAGE_LENGTH', '4000'))
        
        logger.info("Configuration loaded successfully")
    
    @staticmethod
    def _get_required_env(key: str) -> str:
        """
        Get required environment variable or raise error.
        
        Args:
            key: Environment variable name
            
        Returns:
            Environment variable value
            
        Raises:
            ValueError: If environment variable is not set
        """
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value
    
    def validate(self) -> bool:
        """
        Validate configuration settings.
        
        Returns:
            True if configuration is valid
        """
        if not self.telegram_token:
            logger.error("Telegram bot token is not configured")
            return False
        
        if not self.anthropic_api_key:
            logger.error("Anthropic API key is not configured")
            return False
        
        if not self.openai_api_key:
            logger.error("OpenAI API key is not configured")
            return False
        
        logger.info("Configuration validation passed")
        return True


# Global configuration instance
config = Config()
