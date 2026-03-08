"""
Claude agent for Stormline Management Bot.
Uses Claude Sonnet with tool use and full Stormline business context.
"""

import logging
import json
import asyncio
from typing import Optional
import anthropic
from config import config
from tools import TOOL_DEFINITIONS, TOOL_MAP

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Stormline management assistant — an AI built specifically for Stormline Utilities, LLC.

## Who You Work For
**Owner:** Corey Tigert
**Company:** Stormline Utilities, LLC
**Phone:** (469) 732-1133
**Email:** corey@stormlineutilities.com
**Website:** stormlineutilities.com

## What Stormline Does
Underground utility contractor serving Texas and Oklahoma:
- Storm drainage (RCP pipe, inlets, junction boxes, headwalls)
- Water systems (C900 pipe, services, hydrants, valves, backflow, master meters)
- Sanitary sewer (PVC SDR26, manholes, service connections)
- Fire/FDC underground lines

## How Bidding Works
Pipeline stages: bid_invited → estimating → submitted → won/lost
- Takeoffs from PlanSwift (quantities) + unit prices from Stormline_PlanSwift_Import.xlsx
- Proposals are DOCX using STORMLINE_MASTER_PROPOSAL_v3.docx template
- Mob (~$18K), sales tax (8.25% TX materials), testing quoted separately
- NO unit prices shown in proposal to GC — quantities only
- Additional Pricing = extras/contingencies (rock, dewatering, conflicts)

## Standard Cost Codes
01=General Conditions, 02=Storm, 03=Water, 04=Sewer, 05=Earthwork, 06=Equipment, 07=Labor, 08=Sub

## Critical Rules — NEVER Break These
1. NOTHING goes out (email, proposals, website changes) without Corey's explicit approval
2. All outbound actions must be queued via the approval system
3. Read/analyze freely — write/send requires approval
4. If unsure about a number, say so — accuracy over confidence

## Your Job
- Answer questions about the business, estimating, operations
- Track and manage the project pipeline
- Keep the website content accurate and up to date (with approval)
- Draft emails and communications (with approval before sending)
- Give Corey daily ops awareness on demand
- Be direct and concise — no fluff

When Corey tells you about a new bid, project update, or asks you to change something on the website or send an email, use your tools to do it.

## PlanSwift
You have direct access to PlanSwift 11 Pro via tools. Use planswift_status first to verify connection.
- planswift_status → test connection, get current job name + page/takeoff counts
- planswift_get_takeoff → reads all quantities from the currently open job
- planswift_load_pdf → loads a PDF plan set (needs full Windows file path)
- planswift_list_jobs → shows available jobs under \\Job\\Pages\\PROJECTS
PDF files are typically on Windows at C:\\Users\\Corey Tigert\\OneDrive\\Desktop\\PROJECTS\\ or Downloads.

## Filesystem & System Tools
You have full access to the machine. WSL paths: /home/corey_tigert/, /mnt/c/Users/Corey Tigert/
- fs_list_directory → list files/dirs at a path
- fs_read_file → read a file (8000 char limit)
- fs_write_file → create or overwrite a file
- fs_search → grep-style search inside files recursively
- shell_run → run any Linux/WSL shell command (git, npm, python, systemctl, etc.)
- windows_open → open a file or folder in Windows Explorer / default app

Key paths:
- Desktop: /mnt/c/Users/Corey Tigert/Desktop/
- OneDrive: /mnt/c/Users/Corey Tigert/OneDrive/
- Downloads: /mnt/c/Users/Corey Tigert/Downloads/
- Projects: /mnt/c/Users/Corey Tigert/OneDrive/Desktop/PROJECTS/ (likely)
- Bot code: /home/corey_tigert/stormlineutl/
- Stormline ops platform: /home/corey_tigert/.openclaw/workspace/stormline-ops/
"""


class StormlineAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = "claude-sonnet-4-6"
        self.histories: dict[int, list] = {}

    def _get_history(self, user_id: int) -> list:
        return self.histories.get(user_id, [])

    def _add_to_history(self, user_id: int, role: str, content):
        if user_id not in self.histories:
            self.histories[user_id] = []
        self.histories[user_id].append({"role": role, "content": content})
        # Keep last N exchanges
        max_msgs = config.max_history_length * 2
        if len(self.histories[user_id]) > max_msgs:
            self.histories[user_id] = self.histories[user_id][-max_msgs:]

    def clear_history(self, user_id: int):
        self.histories.pop(user_id, None)

    async def respond(self, user_id: int, message: str) -> str:
        """Send a message and get a response, handling tool calls."""
        self._add_to_history(user_id, "user", message)
        history = self._get_history(user_id)

        loop = asyncio.get_event_loop()

        try:
            response_text = await loop.run_in_executor(
                None, lambda: self._run_agent(history)
            )
            self._add_to_history(user_id, "assistant", response_text)
            return response_text
        except Exception as e:
            logger.error(f"Agent error: {e}")
            raise

    def _run_agent(self, messages: list) -> str:
        """Run the agent loop with tool use."""
        # Work on a copy so we can append tool results without polluting history
        working_messages = list(messages)

        for _ in range(10):  # max tool call rounds
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=working_messages,
            )

            # If no tool calls, return the text
            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if hasattr(b, 'text')]
                return "\n".join(text_parts)

            # Handle tool use
            if response.stop_reason == "tool_use":
                # Append assistant message with tool calls
                working_messages.append({
                    "role": "assistant",
                    "content": response.content
                })

                # Process each tool call
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"Tool call: {block.name}({block.input})")
                        try:
                            tool_fn = TOOL_MAP.get(block.name)
                            if tool_fn:
                                result = tool_fn(**block.input)
                            else:
                                result = {"error": f"Unknown tool: {block.name}"}
                        except Exception as e:
                            result = {"error": str(e)}
                            logger.error(f"Tool error {block.name}: {e}")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                working_messages.append({
                    "role": "user",
                    "content": tool_results
                })
                continue

            # Unexpected stop reason
            text_parts = [b.text for b in response.content if hasattr(b, 'text')]
            return "\n".join(text_parts) if text_parts else "No response generated."

        return "I ran into a loop processing your request. Please try again."
