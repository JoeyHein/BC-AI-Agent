"""
Weekly Email Agent API
Generate newsletter emails via Claude and send via Mailchimp
"""

import logging
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import SessionLocal
from app.db.models import User, UserRole, EmailCampaign
from app.services.auth_service import auth_service
from app.config import settings

router = APIRouter(prefix="/api/email-agent", tags=["email-agent"])
logger = logging.getLogger(__name__)

security = HTTPBearer()


# ============================================================================
# DEPENDENCIES
# ============================================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user_id = int(payload.get("sub", 0))
    user = auth_service.get_user_by_id(db, user_id=user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not auth_service.check_permission(current_user, UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class EmailBrief(BaseModel):
    what_happened: str
    coming_up: Optional[str] = None
    tone: str = "Friendly & casual"
    promo_mention: Optional[str] = None
    subject_idea: Optional[str] = None


class EmailDraft(BaseModel):
    subject: str
    preheader: str
    body_html: str
    body_text: str
    internal_notes: str


class SendRequest(BaseModel):
    subject: str
    preheader: str
    body_html: str
    body_text: str
    brief_summary: Optional[str] = None


# ============================================================================
# CLAUDE SYSTEM PROMPT
# ============================================================================

SYSTEM_PROMPT = """You are the voice of Joey Heinrichs, President of OPENDC — a garage door distribution and aluminum door fabrication company based in Medicine Hat, Alberta.

OPENDC supplies dealers and contractors across Western Canada with garage doors, hardware, springs, and aluminum doors. Joey is direct, knowledgeable, unpretentious, and genuinely cares about his dealers and clients succeeding.

Write a weekly email newsletter from Joey to OPENDC's dealer/client list. The email should:

- Feel like it came from a real person, not a marketing department
- Be conversational and warm but not fluffy
- Be 200-350 words — short enough to actually get read
- Have a strong subject line if one isn't provided
- Include a brief story or real moment from the week where possible
- End with a soft CTA (reply to this email, call us, visit the portal, etc.)
- NOT include pricing or specific inventory numbers
- NOT sound like a press release or corporate newsletter

Format the response as JSON:
{
  "subject": "...",
  "preheader": "...",
  "body_html": "...",
  "body_text": "...",
  "internal_notes": "..."
}

The HTML should use a clean, minimal email-safe design:
- Max width 600px centered
- OPENDC brand feel: dark header (#1a1a1a), white body, orange/amber accent (#E07B00) for links and highlights
- Readable body font (Georgia or similar email-safe serif for body, sans-serif for header)
- Mobile responsive inline styles
- Footer with unsubscribe link placeholder: {{unsubscribe_link}}
- No images required — text-first design that looks intentional

IMPORTANT: Return ONLY valid JSON, no markdown code fences or other text."""


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/generate")
async def generate_email(brief: EmailBrief, current_user: User = Depends(require_admin)):
    """Generate a newsletter email draft using Claude."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="Anthropic SDK not installed")

    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    # Build user message from brief
    user_message = f"""Here's what I need for this week's email:

**What happened this week:** {brief.what_happened}
"""
    if brief.coming_up:
        user_message += f"\n**Anything coming up:** {brief.coming_up}"
    if brief.promo_mention:
        user_message += f"\n**Product/promo to mention:** {brief.promo_mention}"
    if brief.subject_idea:
        user_message += f"\n**Subject line idea:** {brief.subject_idea}"
    user_message += f"\n**Tone:** {brief.tone}"

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )

        raw_text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

        draft = json.loads(raw_text)

        return {
            "success": True,
            "draft": {
                "subject": draft.get("subject", ""),
                "preheader": draft.get("preheader", ""),
                "body_html": draft.get("body_html", ""),
                "body_text": draft.get("body_text", ""),
                "internal_notes": draft.get("internal_notes", ""),
            }
        }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        raise HTTPException(status_code=500, detail="AI returned invalid format. Please try again.")
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        raise HTTPException(status_code=500, detail=f"AI service error: {str(e)}")
    except Exception as e:
        logger.error(f"Email generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send")
async def send_email(
    req: SendRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Send the email via Mailchimp."""
    try:
        import mailchimp_marketing as MailchimpMarketing
        from mailchimp_marketing.api_client import ApiClientError
    except ImportError:
        raise HTTPException(status_code=500, detail="mailchimp_marketing package not installed. Run: pip install mailchimp-marketing")

    mc_api_key = settings.MAILCHIMP_API_KEY
    mc_server = settings.MAILCHIMP_SERVER_PREFIX
    mc_audience = settings.MAILCHIMP_AUDIENCE_ID

    if not all([mc_api_key, mc_server, mc_audience]):
        raise HTTPException(
            status_code=500,
            detail="Mailchimp not configured. Set MAILCHIMP_API_KEY, MAILCHIMP_SERVER_PREFIX, and MAILCHIMP_AUDIENCE_ID in .env"
        )

    if not req.subject.strip():
        raise HTTPException(status_code=400, detail="Subject line cannot be empty")

    client = MailchimpMarketing.Client()
    client.set_config({"api_key": mc_api_key, "server": mc_server})

    try:
        # 1. Create campaign
        campaign = client.campaigns.create({
            "type": "regular",
            "recipients": {"list_id": mc_audience},
            "settings": {
                "subject_line": req.subject,
                "preview_text": req.preheader,
                "from_name": settings.MAILCHIMP_FROM_NAME,
                "reply_to": settings.MAILCHIMP_FROM_EMAIL,
                "title": f"Weekly Update - {datetime.utcnow().strftime('%b %d, %Y')}",
            }
        })
        campaign_id = campaign["id"]

        # 2. Set content
        client.campaigns.set_content(campaign_id, {
            "html": req.body_html,
            "plain_text": req.body_text,
        })

        # 3. Send
        client.campaigns.send(campaign_id)

        # 4. Get audience count
        audience = client.lists.get_list(mc_audience)
        member_count = audience.get("stats", {}).get("member_count", 0)

        # 5. Log to database
        campaign_record = EmailCampaign(
            subject=req.subject,
            mailchimp_campaign_id=campaign_id,
            recipient_count=member_count,
            brief_summary=(req.brief_summary or req.subject)[:200],
            sent_by=current_user.id,
        )
        db.add(campaign_record)
        db.commit()

        return {
            "success": True,
            "campaign_id": campaign_id,
            "recipient_count": member_count,
            "sent_at": datetime.utcnow().isoformat(),
            "message": f"Email sent to {member_count} subscribers"
        }

    except ApiClientError as e:
        logger.error(f"Mailchimp API error: {e.text}")
        raise HTTPException(status_code=500, detail=f"Mailchimp error: {e.text}")
    except Exception as e:
        logger.error(f"Send failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audience-count")
async def get_audience_count(current_user: User = Depends(require_admin)):
    """Get the current Mailchimp audience subscriber count."""
    try:
        import mailchimp_marketing as MailchimpMarketing
        from mailchimp_marketing.api_client import ApiClientError
    except ImportError:
        raise HTTPException(status_code=500, detail="mailchimp_marketing package not installed")

    mc_api_key = settings.MAILCHIMP_API_KEY
    mc_server = settings.MAILCHIMP_SERVER_PREFIX
    mc_audience = settings.MAILCHIMP_AUDIENCE_ID

    if not all([mc_api_key, mc_server, mc_audience]):
        return {"success": False, "configured": False, "count": 0}

    client = MailchimpMarketing.Client()
    client.set_config({"api_key": mc_api_key, "server": mc_server})

    try:
        audience = client.lists.get_list(mc_audience)
        return {
            "success": True,
            "configured": True,
            "count": audience.get("stats", {}).get("member_count", 0),
            "audience_name": audience.get("name", ""),
        }
    except ApiClientError as e:
        logger.error(f"Mailchimp error: {e.text}")
        return {"success": False, "configured": True, "count": 0, "error": e.text}


@router.get("/history")
async def get_send_history(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get past email campaign history."""
    campaigns = (
        db.query(EmailCampaign)
        .order_by(EmailCampaign.sent_at.desc())
        .limit(50)
        .all()
    )

    return {
        "success": True,
        "campaigns": [
            {
                "id": c.id,
                "sent_at": c.sent_at.isoformat() if c.sent_at else None,
                "subject": c.subject,
                "mailchimp_campaign_id": c.mailchimp_campaign_id,
                "recipient_count": c.recipient_count,
                "brief_summary": c.brief_summary,
            }
            for c in campaigns
        ]
    }
