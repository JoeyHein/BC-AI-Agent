"""
AI Chat API Endpoints

Provides endpoints for the AI chat interface that allows users
to control Business Central through natural language.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.agent_service import bc_agent_service

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])


# ==================== Request/Response Models ====================

class ChatMessageRequest(BaseModel):
    """Request to send a message to the AI agent"""
    message: str = Field(..., description="The user's message")
    context: Dict[str, Any] = Field(default={}, description="Page context (page, selectedDate, etc.)")
    conversation_id: Optional[int] = Field(None, description="Existing conversation ID to continue")


class ActionTaken(BaseModel):
    """An action taken by the agent"""
    tool: str
    input: Dict[str, Any]
    result: Dict[str, Any]


class ChatMessageResponse(BaseModel):
    """Response from the AI agent"""
    success: bool
    response: str
    actions_taken: List[ActionTaken] = []
    conversation_id: Optional[int] = None
    tokens_used: Optional[int] = None


class ConversationSummary(BaseModel):
    """Summary of a conversation"""
    id: int
    title: str
    createdAt: str
    updatedAt: Optional[str] = None


class MessageDetail(BaseModel):
    """Detail of a chat message"""
    id: int
    conversationId: int
    role: str
    content: str
    context: Optional[Dict[str, Any]] = None
    actionsTaken: Optional[List[Dict[str, Any]]] = None
    tokensUsed: Optional[int] = None
    createdAt: str


class ConversationHistoryResponse(BaseModel):
    """Response with conversation history"""
    success: bool
    conversation: Optional[ConversationSummary] = None
    messages: List[MessageDetail] = []
    error: Optional[str] = None


class ConversationsListResponse(BaseModel):
    """Response with list of conversations"""
    success: bool
    conversations: List[ConversationSummary] = []
    error: Optional[str] = None


# ==================== Endpoints ====================

@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Send a message to the AI agent and get a response.

    The agent can:
    - Answer questions about orders and schedules
    - Execute actions like scheduling orders
    - Provide information from the database

    Context is used to make the agent aware of the current page and any selected items.
    """
    try:
        result = await bc_agent_service.process_message(
            message=request.message,
            context=request.context,
            db=db,
            conversation_id=request.conversation_id
        )

        return ChatMessageResponse(
            success=result.get("success", False),
            response=result.get("response", "No response generated"),
            actions_taken=[
                ActionTaken(**action) for action in result.get("actions_taken", [])
            ],
            conversation_id=result.get("conversation_id"),
            tokens_used=result.get("tokens_used")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations", response_model=ConversationsListResponse)
async def get_conversations(
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    Get a list of recent conversations.

    Returns the most recent conversations ordered by last update.
    """
    try:
        result = await bc_agent_service.get_conversations(db=db, limit=limit)

        if not result.get("success"):
            return ConversationsListResponse(
                success=False,
                error=result.get("error", "Unknown error")
            )

        return ConversationsListResponse(
            success=True,
            conversations=[
                ConversationSummary(**conv) for conv in result.get("conversations", [])
            ]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    conversation_id: int,
    db: Session = Depends(get_db)
):
    """
    Get the message history for a specific conversation.

    Returns all messages in chronological order.
    """
    try:
        result = await bc_agent_service.get_conversation_history(
            db=db,
            conversation_id=conversation_id
        )

        if not result.get("success"):
            return ConversationHistoryResponse(
                success=False,
                error=result.get("error", "Conversation not found")
            )

        return ConversationHistoryResponse(
            success=True,
            conversation=ConversationSummary(**result.get("conversation", {})),
            messages=[MessageDetail(**msg) for msg in result.get("messages", [])]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a conversation and all its messages.
    """
    from app.db.models import Conversation

    try:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Soft delete by marking as inactive
        conversation.is_active = False
        db.commit()

        return {
            "success": True,
            "message": f"Conversation {conversation_id} deleted"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/clear")
async def clear_conversation(
    conversation_id: int,
    db: Session = Depends(get_db)
):
    """
    Clear all messages in a conversation but keep the conversation.
    """
    from app.db.models import Conversation, ChatMessage

    try:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Delete all messages
        db.query(ChatMessage).filter(
            ChatMessage.conversation_id == conversation_id
        ).delete()

        db.commit()

        return {
            "success": True,
            "message": f"Conversation {conversation_id} cleared"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
