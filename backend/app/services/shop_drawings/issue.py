"""Attach an issued shop drawing to a saved quote.

Revision 0 is the first issue. Each later edit of the door config becomes
the next revision and replaces the stored PDF and DXF. DRAWN BY is the
person who saved, not the customer the quote is for.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _drawn_by_name(user) -> str:
    name = (getattr(user, "name", None) or "").strip()
    return name or (getattr(user, "email", None) or "")


def config_fingerprint(config_data: Optional[dict]) -> str:
    try:
        return json.dumps(config_data or {}, sort_keys=True, default=str)
    except TypeError:
        return repr(config_data)


def issue_shop_drawing(config, user, *, revision: int) -> None:
    """Generate and store the drawing for ``revision``.

    Failures are logged and leave the previous bytes in place when this is
    a re-issue. The quote save itself should still succeed.
    """
    from app.services.shop_drawings.framing import generate_framing_drawing

    number = config.shop_drawing_number or f"SD-{int(config.id):06d}"
    drawn_by = _drawn_by_name(user)
    job = config.bc_quote_number or config.name or number
    try:
        pdf = generate_framing_drawing(
            config_data=config.config_data or {},
            customer_name=getattr(user, "company_name", None) or drawn_by,
            job_number=job,
            fmt="pdf",
            drawing_date=datetime.utcnow(),
            config_id=config.id,
            drawn_by=drawn_by,
            drawing_number=number,
            revision=revision,
            project_name=(config.config_data or {}).get("projectName") or config.name or "",
            architect=(config.config_data or {}).get("architect") or "",
        )
        dxf = generate_framing_drawing(
            config_data=config.config_data or {},
            customer_name=getattr(user, "company_name", None) or drawn_by,
            job_number=job,
            fmt="dxf",
            drawing_date=datetime.utcnow(),
            config_id=config.id,
            drawn_by=drawn_by,
            drawing_number=number,
            revision=revision,
            project_name=(config.config_data or {}).get("projectName") or config.name or "",
            architect=(config.config_data or {}).get("architect") or "",
        )
    except Exception:
        logger.exception("Shop drawing generation failed for quote %s", getattr(config, "id", None))
        return

    config.shop_drawing_number = number
    config.shop_drawing_revision = revision
    config.shop_drawing_pdf = pdf
    config.shop_drawing_dxf = dxf
    config.shop_drawn_by = drawn_by
    config.shop_drawing_generated_at = datetime.utcnow()
