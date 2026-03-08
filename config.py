"""
Configuration for Stormline Management Bot.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)

logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        self.telegram_token: str = self._require('TELEGRAM_BOT_TOKEN')
        self.anthropic_api_key: str = self._require('ANTHROPIC_API_KEY')
        self.max_history_length: int = int(os.getenv('MAX_HISTORY_LENGTH', '20'))
        self.max_message_length: int = int(os.getenv('MAX_MESSAGE_LENGTH', '4000'))
        self.allowed_chat_id: int = int(os.getenv('ALLOWED_CHAT_ID', '6830687114'))

        # Paths
        base = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(base)
        self.website_path: str = os.path.join(
            os.path.expanduser('~'), '.openclaw', 'workspace', 'stormline-website', 'index.html'
        )
        self.data_dir: str = os.path.join(base, 'data')
        self.projects_file: str = os.path.join(self.data_dir, 'projects.json')
        self.approvals_file: str = os.path.join(self.data_dir, 'approvals.json')

        os.makedirs(self.data_dir, exist_ok=True)
        logger.info("Config loaded")

    @staticmethod
    def _require(key: str) -> str:
        val = os.getenv(key)
        if not val:
            raise ValueError(f"Missing required env var: {key}")
        return val


config = Config()
