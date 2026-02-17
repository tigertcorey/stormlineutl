"""
AI Model integrations for Stormline UTL Bot.
Handles interactions with Anthropic Claude and OpenAI GPT-4 APIs.
"""

import logging
from typing import Optional, List, Dict
import anthropic
import openai
from config import config
from utils import retry_with_backoff, truncate_text

logger = logging.getLogger(__name__)


class ClaudeModel:
    """Wrapper for Anthropic Claude API."""
    
    def __init__(self):
        """Initialize Claude client."""
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = "claude-3-5-sonnet-20241022"
        logger.info("Claude model initialized")
    
    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def generate_response(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Generate response from Claude.
        
        Args:
            message: User message
            conversation_history: Optional conversation history
            
        Returns:
            Claude's response
            
        Raises:
            Exception: If API call fails after retries
        """
        try:
            # Build messages list
            messages = []
            
            if conversation_history:
                # Add conversation history
                messages.extend(conversation_history)
            
            # Add current message
            messages.append({
                "role": "user",
                "content": message
            })
            
            logger.debug(f"Sending request to Claude with {len(messages)} messages")
            
            # Call Claude API in thread pool to avoid blocking event loop
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=messages
                )
            )
            
            # Extract text from response
            result = response.content[0].text
            logger.info(f"Received response from Claude ({len(result)} chars)")
            
            return truncate_text(result, config.max_message_length)
            
        except anthropic.RateLimitError as e:
            logger.error(f"Claude rate limit exceeded: {e}")
            raise Exception("Rate limit exceeded. Please try again later.")
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise Exception(f"Claude API error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error calling Claude: {e}")
            raise


class GPTModel:
    """Wrapper for OpenAI GPT-4 API."""
    
    def __init__(self):
        """Initialize GPT-4 client."""
        self.client = openai.AsyncOpenAI(api_key=config.openai_api_key)
        self.model = "gpt-4"
        logger.info("GPT-4 model initialized")
    
    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def generate_response(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Generate response from GPT-4.
        
        Args:
            message: User message
            conversation_history: Optional conversation history
            
        Returns:
            GPT-4's response
            
        Raises:
            Exception: If API call fails after retries
        """
        try:
            # Build messages list
            messages = []
            
            if conversation_history:
                # Add conversation history
                messages.extend(conversation_history)
            
            # Add current message
            messages.append({
                "role": "user",
                "content": message
            })
            
            logger.debug(f"Sending request to GPT-4 with {len(messages)} messages")
            
            # Call GPT-4 API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=4096
            )
            
            # Extract text from response
            result = response.choices[0].message.content
            logger.info(f"Received response from GPT-4 ({len(result)} chars)")
            
            return truncate_text(result, config.max_message_length)
            
        except openai.RateLimitError as e:
            logger.error(f"GPT-4 rate limit exceeded: {e}")
            raise Exception("Rate limit exceeded. Please try again later.")
        except openai.APIError as e:
            logger.error(f"GPT-4 API error: {e}")
            raise Exception(f"GPT-4 API error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error calling GPT-4: {e}")
            raise


class MultiModelOrchestrator:
    """Orchestrates multiple AI models and synthesizes responses."""
    
    def __init__(self):
        """Initialize model orchestrator."""
        self.claude = ClaudeModel()
        self.gpt = GPTModel()
        logger.info("Multi-model orchestrator initialized")
    
    async def query_claude(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Query only Claude model.
        
        Args:
            message: User message
            conversation_history: Optional conversation history
            
        Returns:
            Claude's response
        """
        return await self.claude.generate_response(message, conversation_history)
    
    async def query_gpt(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Query only GPT-4 model.
        
        Args:
            message: User message
            conversation_history: Optional conversation history
            
        Returns:
            GPT-4's response
        """
        return await self.gpt.generate_response(message, conversation_history)
    
    async def query_both(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> tuple[str, str, str]:
        """
        Query both models and synthesize response.
        
        Args:
            message: User message
            conversation_history: Optional conversation history
            
        Returns:
            Tuple of (synthesized_response, claude_response, gpt_response)
        """
        import asyncio
        
        # Query both models in parallel
        try:
            claude_response, gpt_response = await asyncio.gather(
                self.claude.generate_response(message, conversation_history),
                self.gpt.generate_response(message, conversation_history),
                return_exceptions=True
            )
            
            # Handle failures gracefully
            if isinstance(claude_response, Exception):
                logger.error(f"Claude failed: {claude_response}")
                claude_response = "⚠️ Claude temporarily unavailable"
                if isinstance(gpt_response, Exception):
                    raise Exception("Both models failed")
                return gpt_response, claude_response, gpt_response
            
            if isinstance(gpt_response, Exception):
                logger.error(f"GPT-4 failed: {gpt_response}")
                gpt_response = "⚠️ GPT-4 temporarily unavailable"
                return claude_response, claude_response, gpt_response
            
            # Synthesize response using GPT-4
            synthesized = await self._synthesize_responses(
                message,
                claude_response,
                gpt_response
            )
            
            return synthesized, claude_response, gpt_response
            
        except Exception as e:
            logger.error(f"Error querying both models: {e}")
            raise
    
    async def _synthesize_responses(
        self,
        original_message: str,
        claude_response: str,
        gpt_response: str
    ) -> str:
        """
        Synthesize responses from both models into a consensus answer.
        
        Args:
            original_message: Original user message
            claude_response: Claude's response
            gpt_response: GPT-4's response
            
        Returns:
            Synthesized response
        """
        # Truncate responses for synthesis to avoid token limits
        max_synthesis_length = 2000
        claude_truncated = truncate_text(claude_response, max_synthesis_length)
        gpt_truncated = truncate_text(gpt_response, max_synthesis_length)
        
        synthesis_prompt = f"""You are a synthesis AI. Given a user question and two AI responses, 
create a single, comprehensive answer that combines the best insights from both responses.

User Question: {original_message}

Claude's Response: {claude_truncated}

GPT-4's Response: {gpt_truncated}

Provide a synthesized answer that:
1. Combines the strongest points from both responses
2. Resolves any contradictions thoughtfully
3. Is clear, concise, and directly addresses the user's question
4. Does not mention that you are synthesizing responses

Synthesized Answer:"""
        
        try:
            # Use GPT-4 for synthesis
            synthesized = await self.gpt.generate_response(
                synthesis_prompt,
                conversation_history=None  # No history for synthesis
            )
            return synthesized
        except Exception as e:
            logger.error(f"Synthesis failed: {e}. Falling back to Claude response.")
            # Fallback to Claude's response
            return claude_response
