"""
BC Agent Service

AI-powered agent that can control Business Central through natural language.
Uses Claude's tool calling to execute actions based on user requests.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.services.agent_tools import AgentTools, AGENT_TOOLS, PHASE1_READ_ONLY_TOOLS
from app.db.models import Conversation, ChatMessage

logger = logging.getLogger(__name__)


class BCAgentService:
    """AI Agent that can control BC through natural language"""

    # Phase configuration - set to 1 for read-only, 2+ for write operations
    CURRENT_PHASE = 1

    def __init__(self):
        self.api_key = settings.ANTHROPIC_API_KEY
        self.client: Optional[Anthropic] = None
        self.model = "claude-sonnet-4-20250514"

        # Select tools based on current phase
        if self.CURRENT_PHASE == 1:
            self.tools = PHASE1_READ_ONLY_TOOLS
            logger.info("BC Agent initialized in Phase 1 (read-only mode)")
        else:
            self.tools = AGENT_TOOLS
            logger.info("BC Agent initialized with full tool access")

        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)
            logger.info("BC Agent service initialized")
        else:
            logger.warning("Anthropic API key not configured. Agent will not work.")

    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build the system prompt with context awareness"""

        today = datetime.now().strftime("%Y-%m-%d")

        # Build context-specific instructions
        context_info = ""
        if context:
            page = context.get("page", "unknown")
            if page == "production_calendar":
                selected_date = context.get("selectedDate")
                context_info = f"""
The user is currently on the Production Calendar page.
{"They have selected the date: " + selected_date if selected_date else "No specific date is selected."}
When they ask about "today" or "this date", use the selected date if available, otherwise use today's date ({today}).
"""
            elif page == "orders":
                context_info = f"""
The user is currently on the Orders Management page.
They can see a list of sales orders and their statuses.
"""
            elif page == "dashboard":
                context_info = f"""
The user is currently on the Dashboard.
They can see an overview of quotes, orders, and production status.
"""

        # Phase-specific capabilities
        if self.CURRENT_PHASE == 1:
            capabilities = """You have access to tools that can:
- Get detailed order information (order details, line items, work orders)
- Search for orders by customer name, order number, or status
- List orders that need scheduling
- View the production schedule for specific dates
- Get production summaries and capacity overview

NOTE: You are currently in READ-ONLY mode. You can look up information but cannot make changes.
If a user asks you to schedule, ship, or modify anything, politely explain that this feature
is coming soon and offer to look up the relevant information instead."""
        else:
            capabilities = """You have access to tools that can:
- Schedule and unschedule sales orders for production dates
- Get detailed order information
- List unscheduled orders
- View the production schedule for specific dates
- Ship completed orders
- Sync data from Business Central"""

        return f"""You are an AI assistant for the BC AI Agent application - a Business Central automation system for Open Distribution Company, a garage door manufacturer.

Today's date is: {today}

{context_info}

{capabilities}

When users ask questions:
1. Use tools to gather information as needed
2. Present the information clearly and concisely
3. Format dates as readable (e.g., "February 15, 2026" or "Feb 15")
4. Format currency values nicely (e.g., "$1,234.56")

Order numbers usually look like "SO-XXXXXX" (e.g., SO-000857).
When a user mentions an order number, try to match it with or without the "SO-" prefix.

Be helpful, concise, and friendly. If you're unsure about something, ask for clarification.
"""

    async def process_message(
        self,
        message: str,
        context: Dict[str, Any],
        db: Session,
        conversation_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process a user message and execute any requested actions.

        Args:
            message: The user's message
            context: Page context (page, selectedDate, etc.)
            db: Database session
            conversation_id: Optional existing conversation ID

        Returns:
            Response with message and actions taken
        """
        if not self.client:
            return {
                "success": False,
                "response": "AI service is not configured. Please check the Anthropic API key.",
                "actions_taken": [],
                "conversation_id": None
            }

        try:
            # Get or create conversation
            if conversation_id:
                conversation = db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
            else:
                conversation = Conversation(
                    title=message[:50] + "..." if len(message) > 50 else message,
                    is_active=True
                )
                db.add(conversation)
                db.flush()

            # Save user message
            user_message = ChatMessage(
                conversation_id=conversation.id,
                role="user",
                content=message,
                context=context
            )
            db.add(user_message)
            db.flush()

            # Build messages for Claude
            system_prompt = self._build_system_prompt(context)

            # Get conversation history (last 10 messages for context)
            history_messages = db.query(ChatMessage).filter(
                ChatMessage.conversation_id == conversation.id
            ).order_by(ChatMessage.created_at.desc()).limit(10).all()

            # Build message history (reverse to chronological order, exclude current message)
            messages = []
            for msg in reversed(history_messages[1:]):  # Exclude the message we just added
                messages.append({
                    "role": msg.role if msg.role in ["user", "assistant"] else "user",
                    "content": msg.content
                })

            # Add current message
            messages.append({
                "role": "user",
                "content": message
            })

            # Initialize tools
            tools_instance = AgentTools(db)
            actions_taken = []
            total_tokens = 0

            # Call Claude with tools (phase-appropriate)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                tools=self.tools,
                messages=messages
            )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            # Process response - handle tool calls
            while response.stop_reason == "tool_use":
                # Extract tool calls from response
                tool_calls = [block for block in response.content if block.type == "tool_use"]

                tool_results = []
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    tool_input = tool_call.input

                    logger.info(f"Executing tool: {tool_name} with input: {tool_input}")

                    # Execute the tool
                    result = await self._execute_tool(tools_instance, tool_name, tool_input)

                    actions_taken.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "result": result
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": json.dumps(result)
                    })

                # Add assistant's response and tool results to messages
                messages.append({
                    "role": "assistant",
                    "content": response.content
                })
                messages.append({
                    "role": "user",
                    "content": tool_results
                })

                # Continue the conversation with tool results
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=self.tools,
                    messages=messages
                )

                total_tokens += response.usage.input_tokens + response.usage.output_tokens

            # Extract final text response
            final_response = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_response += block.text

            # Save assistant message
            assistant_message = ChatMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=final_response,
                context=context,
                actions_taken=actions_taken if actions_taken else None,
                tokens_used=total_tokens
            )
            db.add(assistant_message)

            # Update conversation timestamp
            conversation.updated_at = datetime.utcnow()

            db.commit()

            return {
                "success": True,
                "response": final_response,
                "actions_taken": actions_taken,
                "conversation_id": conversation.id,
                "tokens_used": total_tokens
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Error processing message: {e}", exc_info=True)
            return {
                "success": False,
                "response": f"An error occurred: {str(e)}",
                "actions_taken": [],
                "conversation_id": conversation_id
            }

    async def _execute_tool(
        self,
        tools: AgentTools,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool and return the result"""
        try:
            if tool_name == "schedule_order":
                return await tools.schedule_order(
                    order_identifier=tool_input.get("order_identifier"),
                    target_date=tool_input.get("date")
                )

            elif tool_name == "unschedule_order":
                return await tools.unschedule_order(
                    order_identifier=tool_input.get("order_identifier")
                )

            elif tool_name == "get_order_details":
                return await tools.get_order_details(
                    order_identifier=tool_input.get("order_identifier")
                )

            elif tool_name == "list_unscheduled_orders":
                return await tools.list_unscheduled_orders()

            elif tool_name == "get_schedule_for_date":
                return await tools.get_schedule_for_date(
                    target_date=tool_input.get("date"),
                    date_to=tool_input.get("date_to")
                )

            elif tool_name == "ship_order":
                return await tools.ship_order(
                    order_identifier=tool_input.get("order_identifier")
                )

            elif tool_name == "sync_from_bc":
                return await tools.sync_from_bc(
                    sync_type=tool_input.get("sync_type")
                )

            elif tool_name == "search_orders":
                return await tools.search_orders(
                    query=tool_input.get("query", ""),
                    status=tool_input.get("status"),
                    limit=tool_input.get("limit", 10)
                )

            elif tool_name == "get_production_summary":
                return await tools.get_production_summary(
                    date_from=tool_input.get("date_from"),
                    date_to=tool_input.get("date_to")
                )

            else:
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}"
                }

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def get_conversation_history(
        self,
        db: Session,
        conversation_id: int
    ) -> Dict[str, Any]:
        """Get messages for a conversation"""
        try:
            conversation = db.query(Conversation).filter(
                Conversation.id == conversation_id
            ).first()

            if not conversation:
                return {
                    "success": False,
                    "error": "Conversation not found"
                }

            messages = db.query(ChatMessage).filter(
                ChatMessage.conversation_id == conversation_id
            ).order_by(ChatMessage.created_at.asc()).all()

            return {
                "success": True,
                "conversation": {
                    "id": conversation.id,
                    "title": conversation.title,
                    "createdAt": conversation.created_at.isoformat(),
                    "updatedAt": conversation.updated_at.isoformat() if conversation.updated_at else None
                },
                "messages": [msg.to_dict() for msg in messages]
            }

        except Exception as e:
            logger.error(f"Error getting conversation history: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def get_conversations(
        self,
        db: Session,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get list of recent conversations"""
        try:
            conversations = db.query(Conversation).filter(
                Conversation.is_active == True
            ).order_by(Conversation.updated_at.desc()).limit(limit).all()

            return {
                "success": True,
                "conversations": [
                    {
                        "id": conv.id,
                        "title": conv.title,
                        "createdAt": conv.created_at.isoformat(),
                        "updatedAt": conv.updated_at.isoformat() if conv.updated_at else None
                    }
                    for conv in conversations
                ]
            }

        except Exception as e:
            logger.error(f"Error getting conversations: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


# Singleton instance
bc_agent_service = BCAgentService()
