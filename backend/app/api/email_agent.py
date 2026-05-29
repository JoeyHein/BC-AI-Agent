"""
Weekly Email Agent API
Generate newsletter emails via Claude and send via Mailchimp
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
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


class TestSendRequest(BaseModel):
    subject: str
    preheader: str
    body_html: str
    body_text: str
    test_email: Optional[str] = None  # defaults to the configured from-email


class ScheduleRequest(BaseModel):
    subject: str
    preheader: str
    body_html: str
    body_text: str
    brief_summary: Optional[str] = None
    # ISO 8601 instant for the send. Sent by the browser already converted to UTC.
    schedule_time: str


class UnscheduleRequest(BaseModel):
    campaign_id: str


# ============================================================================
# BRANDING
# ============================================================================

# Hosted on the portal (served by nginx). Used as the email header logo.
OPENDC_LOGO_URL = "https://portal.opendc.ca/assets/opendc-logo.jpg"
BRAND_DARK = "#1a1a1a"
BRAND_AMBER = "#E07B00"
COMPANY_ADDRESS = "Open Distribution Company &bull; 617 18 St SW, Medicine Hat, AB T1A 7Y1"


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

The HTML must use this EXACT branded structure so every email looks consistent. Do not change the header or footer — only write the body content between them.

Header (use verbatim, including the logo):
<div style="background-color:#1a1a1a;padding:24px;text-align:center;">
  <img src="https://portal.opendc.ca/assets/opendc-logo.jpg" alt="OPENDC" width="180" style="max-width:180px;height:auto;display:inline-block;" />
</div>

Body rules:
- Wrap everything in: <body style="margin:0;padding:0;background-color:#f5f5f5;font-family:Georgia,serif;"><div style="max-width:600px;margin:0 auto;background-color:#ffffff;">
- Put the header block (above) first, then a content block: <div style="padding:30px 25px;color:#333333;font-size:16px;line-height:1.6;">...your written content...</div>
- Use the amber accent (#E07B00) for links and the occasional highlighted phrase. Links: style="color:#E07B00;"
- Readable email-safe serif body (Georgia), sans-serif only inside the header
- Mobile responsive inline styles, images max-width:100%

Footer (use verbatim, ends the email):
<div style="background-color:#f5f5f5;padding:20px 25px;text-align:center;color:#999999;font-size:12px;font-family:Arial,sans-serif;">
  <p style="margin:0 0 8px 0;">Open Distribution Company &bull; 617 18 St SW, Medicine Hat, AB T1A 7Y1</p>
  <p style="margin:0;"><a href="*|UNSUB|*" style="color:#999999;text-decoration:underline;">Unsubscribe</a></p>
</div>
Then close: </div></body>

IMPORTANT: Return ONLY valid JSON, no markdown code fences or other text."""


# ============================================================================
# HELPERS
# ============================================================================

def _normalize_schedule_time(raw: str) -> datetime:
    """Parse an ISO instant for a portal-managed scheduled send.

    The portal owns the timing now (a background job fires the free Mailchimp
    send when the moment arrives), so we no longer need Mailchimp's paid
    15-minute-boundary rule. We just normalize to UTC, drop sub-minute
    precision (the queue poller ticks once a minute), and require a small lead
    so a borderline pick doesn't land in the past before the next poll.
    """
    s = (raw or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="A schedule time is required.")
    # Accept a trailing 'Z' (Python <3.11 fromisoformat doesn't).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule time format.")

    # Treat a naive timestamp as UTC; otherwise convert to UTC.
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    dt = dt.replace(second=0, microsecond=0)

    now = datetime.now(timezone.utc)
    if dt <= now + timedelta(minutes=2):
        raise HTTPException(
            status_code=400,
            detail="Schedule time must be at least a couple of minutes in the future.",
        )
    return dt


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


@router.post("/send-test")
async def send_test_email(
    req: TestSendRequest,
    current_user: User = Depends(require_admin),
):
    """Send a test copy of the email to a single address without touching the list.

    Creates a temporary draft campaign, sets content, fires Mailchimp's test send,
    then deletes the draft so it doesn't clutter the Mailchimp account.
    """
    try:
        import mailchimp_marketing as MailchimpMarketing
        from mailchimp_marketing.api_client import ApiClientError
    except ImportError:
        raise HTTPException(status_code=500, detail="mailchimp_marketing package not installed")

    mc_api_key = settings.MAILCHIMP_API_KEY
    mc_server = settings.MAILCHIMP_SERVER_PREFIX
    mc_audience = settings.MAILCHIMP_AUDIENCE_ID

    if not all([mc_api_key, mc_server, mc_audience]):
        raise HTTPException(status_code=500, detail="Mailchimp not configured.")

    if not req.subject.strip():
        raise HTTPException(status_code=400, detail="Subject line cannot be empty")

    test_email = (req.test_email or settings.MAILCHIMP_FROM_EMAIL or "").strip()
    if "@" not in test_email:
        raise HTTPException(status_code=400, detail="A valid test email address is required")

    client = MailchimpMarketing.Client()
    client.set_config({"api_key": mc_api_key, "server": mc_server})

    campaign_id = None
    try:
        campaign = client.campaigns.create({
            "type": "regular",
            "recipients": {"list_id": mc_audience},
            "settings": {
                "subject_line": f"[TEST] {req.subject}",
                "preview_text": req.preheader,
                "from_name": settings.MAILCHIMP_FROM_NAME,
                "reply_to": settings.MAILCHIMP_FROM_EMAIL,
                "title": f"TEST - {datetime.utcnow().strftime('%b %d, %Y %H:%M')}",
            }
        })
        campaign_id = campaign["id"]

        client.campaigns.set_content(campaign_id, {
            "html": req.body_html,
            "plain_text": req.body_text,
        })

        client.campaigns.send_test_email(campaign_id, {
            "test_emails": [test_email],
            "send_type": "html",
        })

        return {
            "success": True,
            "message": f"Test email sent to {test_email}",
            "test_email": test_email,
        }

    except ApiClientError as e:
        logger.error(f"Mailchimp test send error: {e.text}")
        raise HTTPException(status_code=500, detail=f"Mailchimp error: {e.text}")
    except Exception as e:
        logger.error(f"Test send failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up the throwaway draft so the Mailchimp account stays tidy.
        if campaign_id:
            try:
                client.campaigns.remove(campaign_id)
            except Exception as cleanup_err:
                logger.warning(f"Could not delete test campaign {campaign_id}: {cleanup_err}")


@router.post("/schedule")
async def schedule_email(
    req: ScheduleRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Schedule the email to go out at a future time, managed by the portal.

    Mailchimp's native scheduling (campaigns.schedule) is a paid-plan feature,
    so on the free plan we own the timing ourselves: build the campaign as a
    DRAFT at Mailchimp now (create + set_content — both free) and record the
    UTC release time locally with status='scheduled'. The background
    `email_send_queue` job (see scheduler_service) fires the free
    campaigns.send when the moment arrives. No paid feature is touched.
    """
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

    schedule_dt = _normalize_schedule_time(req.schedule_time)

    client = MailchimpMarketing.Client()
    client.set_config({"api_key": mc_api_key, "server": mc_server})

    campaign_id = None
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
                "title": f"Weekly Update - {schedule_dt.strftime('%b %d, %Y')}",
            }
        })
        campaign_id = campaign["id"]

        # 2. Set content — the campaign now exists as a draft at Mailchimp.
        client.campaigns.set_content(campaign_id, {
            "html": req.body_html,
            "plain_text": req.body_text,
        })

        # 3. Leave it as a draft. The portal's email_send_queue job will fire
        #    the free campaigns.send at schedule_dt — we do NOT call the paid
        #    campaigns.schedule here.

        # 4. Audience count (a snapshot — the real count is taken at release)
        audience = client.lists.get_list(mc_audience)
        member_count = audience.get("stats", {}).get("member_count", 0)

        # 5. Log to database (naive UTC, matching sent_at convention)
        schedule_naive = schedule_dt.replace(tzinfo=None)
        campaign_record = EmailCampaign(
            subject=req.subject,
            mailchimp_campaign_id=campaign_id,
            recipient_count=member_count,
            brief_summary=(req.brief_summary or req.subject)[:200],
            sent_by=current_user.id,
            sent_at=schedule_naive,        # timeline anchor for history sorting
            scheduled_at=schedule_naive,
            status="scheduled",
        )
        db.add(campaign_record)
        db.commit()

        return {
            "success": True,
            "campaign_id": campaign_id,
            "recipient_count": member_count,
            "scheduled_at": schedule_dt.isoformat(),
            "message": f"Email scheduled for {schedule_dt.strftime('%b %d, %Y at %H:%M UTC')} to {member_count} subscribers",
        }

    except ApiClientError as e:
        # Clean up the half-built campaign so a failed schedule doesn't litter Mailchimp.
        if campaign_id:
            try:
                client.campaigns.remove(campaign_id)
            except Exception:
                pass
        logger.error(f"Mailchimp schedule error: {e.text}")
        raise HTTPException(status_code=500, detail=f"Mailchimp error: {e.text}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Schedule failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unschedule")
async def unschedule_email(
    req: UnscheduleRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Cancel a portal-scheduled send: delete the Mailchimp draft, mark canceled.

    Since the campaign is only a draft locally queued by the portal (never handed
    to Mailchimp's paid scheduler), canceling means removing the draft so it can't
    be picked up by the email_send_queue job, then marking the local row canceled.
    """
    try:
        import mailchimp_marketing as MailchimpMarketing
        from mailchimp_marketing.api_client import ApiClientError
    except ImportError:
        raise HTTPException(status_code=500, detail="mailchimp_marketing package not installed")

    mc_api_key = settings.MAILCHIMP_API_KEY
    mc_server = settings.MAILCHIMP_SERVER_PREFIX
    if not all([mc_api_key, mc_server]):
        raise HTTPException(status_code=500, detail="Mailchimp not configured.")

    client = MailchimpMarketing.Client()
    client.set_config({"api_key": mc_api_key, "server": mc_server})

    try:
        # Delete the draft so the queue job can't send it. A 404 here (already
        # gone) is fine — we still want to mark the local row canceled.
        client.campaigns.remove(req.campaign_id)
    except ApiClientError as e:
        if e.status_code != 404:
            logger.error(f"Mailchimp remove-draft error: {e.text}")
            raise HTTPException(status_code=500, detail=f"Mailchimp error: {e.text}")

    # Mark the local record canceled (best-effort; the Mailchimp call is the source of truth).
    record = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.mailchimp_campaign_id == req.campaign_id)
        .first()
    )
    if record:
        record.status = "canceled"
        db.commit()

    return {"success": True, "message": "Scheduled send canceled", "campaign_id": req.campaign_id}


@router.post("/upload-image")
async def upload_image(
    image: UploadFile = File(...),
    current_user: User = Depends(require_admin),
):
    """Upload an image to Mailchimp's File Manager (CDN) and return its hosted URL.

    Images are hosted on Mailchimp's CDN — permanent, fast, and reliable in inboxes —
    rather than the portal's container filesystem (which would not survive redeploys).
    """
    try:
        import mailchimp_marketing as MailchimpMarketing
        from mailchimp_marketing.api_client import ApiClientError
    except ImportError:
        raise HTTPException(status_code=500, detail="mailchimp_marketing package not installed")

    mc_api_key = settings.MAILCHIMP_API_KEY
    mc_server = settings.MAILCHIMP_SERVER_PREFIX
    if not all([mc_api_key, mc_server]):
        raise HTTPException(status_code=500, detail="Mailchimp not configured.")

    content_type = (image.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (PNG, JPG, GIF).")

    raw = await image.read()
    # Mailchimp File Manager caps uploads; keep email images reasonable.
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5 MB).")

    import base64
    file_data = base64.b64encode(raw).decode("ascii")
    safe_name = (image.filename or "image").replace("/", "_").replace("\\", "_")

    client = MailchimpMarketing.Client()
    client.set_config({"api_key": mc_api_key, "server": mc_server})

    try:
        result = client.fileManager.upload({"name": safe_name, "file_data": file_data})
        url = result.get("full_size_url") or result.get("thumbnail_url")
        if not url:
            raise HTTPException(status_code=500, detail="Mailchimp did not return an image URL.")
        return {"success": True, "url": url, "name": result.get("name", safe_name)}
    except ApiClientError as e:
        logger.error(f"Mailchimp image upload error: {e.text}")
        raise HTTPException(status_code=500, detail=f"Mailchimp error: {e.text}")
    except Exception as e:
        logger.error(f"Image upload failed: {e}", exc_info=True)
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
                "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
                "status": c.status or "sent",
                "subject": c.subject,
                "mailchimp_campaign_id": c.mailchimp_campaign_id,
                "recipient_count": c.recipient_count,
                "brief_summary": c.brief_summary,
            }
            for c in campaigns
        ]
    }
