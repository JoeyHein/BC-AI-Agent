"""
Daily purchasing brief — the morning narrative over the purchasing numbers.

The demand engine, the RAG board, and the cut queue each answer one question
well, but nobody reads three dashboards before 7am. This service joins them:

  1. FACTS  — a compact, deterministic snapshot of today's buy list, at-risk
              sales orders, cut work orders, and blocker mix.
  2. DIFF   — what moved since the previous brief, computed in PYTHON. The
              model is never asked to remember or re-derive yesterday; it is
              handed the arithmetic and asked to explain it.
  3. BRIEF  — Claude turns (1) + (2) into plain English: what to buy today,
              what's at risk, what changed, what needs a decision.

Everything the model sees is stored on the row, so a brief is reproducible and
tomorrow's diff runs against real numbers. Generation is best-effort by design:
if the API call fails the facts are still persisted and the digest/workbook fall
back to the numeric tables they always had.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import PurchasingBrief
from app.services.purchasing_demand_service import UNASSIGNED

logger = logging.getLogger(__name__)

BRIEF_MODEL = "claude-opus-5"

# How much of each list the model sees. Enough to reason over, small enough that
# the prompt stays cheap and the model doesn't just re-list the tables.
TOP_VENDORS = 8
TOP_ITEMS = 12
TOP_AT_RISK = 12
TOP_CUTS = 6

# A brief this fresh is reused rather than regenerated — the 4am workbook job
# writes it, the 7am digest reads it, and both tell the same story for one API
# call a day.
DEFAULT_MAX_AGE_HOURS = 6


# ── facts ───────────────────────────────────────────────────────────────────

def _est(row: dict) -> float:
    return round((row.get("net_need") or 0) * (row.get("unit_cost") or 0), 2)


def build_facts(
    req: dict,
    so_rows: Optional[List[dict]] = None,
    proposals: Optional[List[dict]] = None,
    today: Optional[date] = None,
) -> dict:
    """Compact the day's computed state into the snapshot the model reads.

    Deliberately lossy: top-N by money and risk, not the whole buy list. The
    brief's job is to point at the few things that need a person today, and a
    full item dump would drown that.
    """
    today = today or date.today()
    s = req.get("summary", {}) or {}
    rows = [r for r in req.get("items", []) if (r.get("net_need") or 0) > 0]

    vendors = []
    for g in (req.get("vendors") or [])[:TOP_VENDORS]:
        vendors.append({
            "vendor": g["vendor_name"],
            "items": g["item_count"],
            "cost": round(g["estimated_cost"], 2),
            "is_expedite": bool(g.get("is_expedite")),
            "unassigned": g["vendor_name"] == UNASSIGNED,
        })

    by_spend = sorted(rows, key=_est, reverse=True)[:TOP_ITEMS]
    items = []
    for r in by_spend:
        items.append({
            "item": r["item_no"],
            "desc": (r.get("description") or "")[:60],
            "need": r["net_need"],
            "uom": r.get("unit_of_measure"),
            "vendor": r.get("vendor_name"),
            "est_cost": _est(r),
            "lead_time_days": r.get("lead_time_days"),
            "on_order": r.get("on_order"),
            "jobs": (r.get("jobs") or [])[:4],
            "last_bought_from": r.get("last_purchase_vendor"),
        })

    # Assigned vendor differs from who we actually last paid — the purchaser
    # should know before a PO goes out to the "wrong" name.
    drift = [
        {"item": r["item_no"], "assigned": r.get("vendor_name"),
         "last_bought_from": r.get("last_purchase_vendor"), "est_cost": _est(r)}
        for r in rows
        if r.get("last_purchase_vendor")
        and r.get("last_purchase_vendor") != r.get("vendor_name")
    ]
    drift.sort(key=lambda d: d["est_cost"], reverse=True)

    expedite_cost = round(sum(
        _est(r) for r in rows if r.get("is_expedite_vendor")
    ), 2)

    facts: Dict[str, Any] = {
        "as_of": today.isoformat(),
        "buy_list": {
            "shortfall_items": s.get("shortfall_items", 0),
            "vendor_count": s.get("vendor_count", 0),
            "unassigned_items": s.get("unassigned_items", 0),
            "estimated_cost": s.get("estimated_cost", 0),
            "horizon_weeks": req.get("horizon_weeks"),
            "deferred_orders": s.get("deferred_orders", 0),
            "production_included": bool(req.get("production_included")),
        },
        "top_vendors": vendors,
        "top_items": items,
        "vendor_drift": drift[:5],
        "expedite_exposure": {"estimated_cost": expedite_cost},
    }

    if so_rows is not None:
        rag = {"red": 0, "amber": 0, "green": 0}
        for r in so_rows:
            rag[r["rag"]] = rag.get(r["rag"], 0) + 1
        at_risk = [r for r in so_rows if r["rag"] in ("red", "amber")][:TOP_AT_RISK]
        facts["orders"] = {
            "open": len(so_rows),
            "red": rag["red"], "amber": rag["amber"], "green": rag["green"],
            "at_risk": [{
                "so": r["so_number"],
                "customer": r.get("customer"),
                "due": r["rdd"].isoformat() if r.get("rdd") else None,
                "days_to_due": (r["rdd"] - today).days if r.get("rdd") else None,
                "rag": r["rag"],
                "why": r.get("rag_reason"),
                "short_items": r.get("short_item_count"),
            } for r in at_risk],
        }

    # What we could NOT see today, stated plainly. A missing feed reads as a
    # zero everywhere downstream, and a brief that reports a confident zero it
    # can't back up is worse than one that says the data was unavailable.
    gaps = []
    if so_rows is None:
        gaps.append("Sales-order RAG board unavailable — no red/amber/green picture today.")
    if proposals is None:
        gaps.append("Cut work-order queue unavailable — cut-instead-of-buy savings not assessed.")
    if not req.get("production_included"):
        gaps.append("Production-order demand NOT included — figures are open sales orders only.")

    if proposals is not None:
        ship_now = [w for w in proposals if w.get("makes_invoiceable")]
        blockers = {"needs_po": 0, "needs_production": 0, "cuttable": 0,
                    "unknown": 0, "on_order": 0}
        for w in proposals:
            for k, v in (w.get("blocker_summary") or {}).items():
                if k in blockers:
                    blockers[k] += v or 0
        facts["cuts"] = {
            "proposals": len(proposals),
            "ship_now": len(ship_now),
            "purchase_avoided": round(sum(w.get("purchase_avoided") or 0 for w in proposals), 2),
            "purchase_avoided_ship_now": round(sum(w.get("purchase_avoided") or 0 for w in ship_now), 2),
            "blockers": blockers,
            "top": [{
                "so": w["so_number"],
                "avoided": round(w.get("purchase_avoided") or 0, 2),
                "ships_now": bool(w.get("makes_invoiceable")),
                "cuts": len(w.get("cuts") or []),
                "blocking_items": len(w.get("blockers") or []),
                "blocker_summary": w.get("blocker_summary"),
            } for w in sorted(
                proposals,
                key=lambda w: (not w.get("makes_invoiceable"), -(w.get("purchase_avoided") or 0)),
            )[:TOP_CUTS]],
        }
        if blockers["unknown"]:
            gaps.append(
                f"{blockers['unknown']} blocking item(s) could not be classified as "
                "buy-vs-make — BC's replenishment data was unavailable for them, so "
                "the PO/production split understates both."
            )

    if gaps:
        facts["data_gaps"] = gaps
    return facts


# ── diff ────────────────────────────────────────────────────────────────────

def _delta(now: Any, before: Any) -> Optional[float]:
    try:
        return round(float(now or 0) - float(before or 0), 2)
    except (TypeError, ValueError):
        return None


def diff_facts(now: dict, prev: Optional[dict]) -> dict:
    """What moved since the previous brief — arithmetic, not model opinion.

    Computed here rather than prompted so the "what changed" section can never
    be a hallucinated trend. The model gets these numbers and explains them.
    """
    if not prev:
        return {"first_brief": True}

    d: Dict[str, Any] = {"prior_as_of": prev.get("as_of")}

    nb, pb = now.get("buy_list", {}), prev.get("buy_list", {})
    d["buy_list"] = {
        "estimated_cost": _delta(nb.get("estimated_cost"), pb.get("estimated_cost")),
        "shortfall_items": _delta(nb.get("shortfall_items"), pb.get("shortfall_items")),
        "unassigned_items": _delta(nb.get("unassigned_items"), pb.get("unassigned_items")),
    }

    if "orders" in now and "orders" in prev:
        no, po = now["orders"], prev["orders"]
        d["orders"] = {
            "open": _delta(no.get("open"), po.get("open")),
            "red": _delta(no.get("red"), po.get("red")),
            "amber": _delta(no.get("amber"), po.get("amber")),
            "green": _delta(no.get("green"), po.get("green")),
        }
        was = {r["so"]: r["rag"] for r in po.get("at_risk", [])}
        now_risk = {r["so"]: r["rag"] for r in no.get("at_risk", [])}
        d["newly_at_risk"] = sorted(set(now_risk) - set(was))
        d["no_longer_at_risk"] = sorted(set(was) - set(now_risk))
        d["worsened"] = sorted(
            so for so, rag in now_risk.items()
            if was.get(so) == "amber" and rag == "red"
        )

    was_items = {i["item"]: i for i in prev.get("top_items", [])}
    now_items = {i["item"]: i for i in now.get("top_items", [])}
    d["new_big_buys"] = sorted(set(now_items) - set(was_items))
    d["cleared_big_buys"] = sorted(set(was_items) - set(now_items))

    if "cuts" in now and "cuts" in prev:
        d["cuts"] = {
            "proposals": _delta(now["cuts"].get("proposals"), prev["cuts"].get("proposals")),
            "ship_now": _delta(now["cuts"].get("ship_now"), prev["cuts"].get("ship_now")),
            "purchase_avoided": _delta(
                now["cuts"].get("purchase_avoided"), prev["cuts"].get("purchase_avoided")
            ),
        }

    return d


# ── the brief ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You write the morning purchasing brief for OPENDC, a garage-door \
manufacturer in Alberta. Your reader is the owner/purchaser: he already knows the \
business, has the full numbers in the tables below your brief, and has about ninety \
seconds. He needs judgement, not a recap.

WHAT THE NUMBERS MEAN
- OPENDC buys to order and runs lean, so demand comes from live sales orders and \
released production orders, netted against on-hand stock and open POs. A "shortfall" \
is genuinely unbought material for committed work.
- A sales order is RED when it is past due or short with no PO and due soon, AMBER when \
there is a gap but still time, GREEN when material is covered. Almost nothing is green — \
BC inventory is under-recorded and manufactured items are not yet exploded to raw \
materials — so treat the RED/AMBER split as the signal, not the absolute count.
- "Cut work orders" are proposals to cut long stock already in the building down to a \
size a job needs instead of buying it. "ships now" means the cut clears the LAST thing \
blocking that order, so it can be invoiced.
- Blockers are split by how they get fixed: needs_po (buy it), needs_production (make it), \
cuttable (cut it from stock).
- An "expedite" vendor is a last-resort supplier used only for sub-one-week turnarounds; \
spend there is worth flagging.
- "vendor_drift" means the vendor on the item card is not who we actually last bought it \
from — worth a look before the PO goes out.

HOW TO WRITE IT
- Lead with the outcome. Every line should be something he can act on or decide.
- Name the specific sales order, item number, vendor, or dollar figure. "Several items are \
short" is useless; "SO-001238 needs 6 x PN40-21400-1800 from UPWARDOR, $1,240" is the job.
- The CHANGE figures given to you are already computed. Explain what they mean; never \
invent a trend, and never state a number that is not in the facts.
- Say plainly when something looks like a data problem rather than a real shortage — an \
item showing short that is clearly stocked, a vendor with no assignment, a due date that \
makes no sense. Surfacing those is part of the job.
- If the facts carry a "data_gaps" list, those feeds were unavailable this morning. Do \
not report a figure that depends on a missing feed as though it were measured — say what \
is unknown, and put it in "watch".
- No preamble, no sign-off, no restating the totals he can see in the table. Short \
sentences. If a section has nothing worth saying, return an empty list for it rather than \
padding.

Return ONLY a JSON object, no prose around it, in exactly this shape:
{
  "headline": "one sentence: the single most important thing about today",
  "buy_today": ["what to order now and why — most urgent first, max 5"],
  "at_risk": ["orders/jobs in trouble and what would unblock each, max 5"],
  "changed": ["what moved since the last brief and what it means, max 4"],
  "decisions": [{"question": "a decision only he can make", "context": "why it matters now"}],
  "watch": ["things not urgent today but worth knowing, incl. suspected data problems, max 3"]
}"""


class PurchasingBriefService:
    """Builds, stores, and renders the daily narrative brief."""

    # ── generation ──────────────────────────────────────────────────────────

    def generate(
        self,
        db: Session,
        req: Optional[dict] = None,
        so_rows: Optional[List[dict]] = None,
        proposals: Optional[List[dict]] = None,
        include_cuts: bool = True,
        today: Optional[date] = None,
    ) -> PurchasingBrief:
        """Build today's facts, diff them against the last brief, and write it.

        Accepts already-computed inputs so a caller that just ran the demand
        engine (the digest, the planning workbook) doesn't pay for it twice.
        Anything not supplied is gathered here, best-effort.
        """
        today = today or date.today()

        if req is None:
            from app.services.purchasing_demand_service import purchasing_demand_service
            req = purchasing_demand_service.compute_requirements(db)

        if so_rows is None:
            so_rows = self._gather_so_rows(req, today)

        if proposals is None and include_cuts:
            proposals = self._gather_proposals(db)

        facts = build_facts(req, so_rows=so_rows, proposals=proposals, today=today)
        prev = self.latest(db)
        diff = diff_facts(facts, (prev.facts_json if prev else None))

        row = PurchasingBrief(
            as_of=today, generated_at=datetime.utcnow(),
            facts_json=facts, diff_json=diff,
        )

        result = self._ask_claude(facts, diff)
        if result.get("success"):
            row.brief_json = result["brief"]
            row.model = result.get("model")
            row.input_tokens = result.get("input_tokens")
            row.output_tokens = result.get("output_tokens")
        else:
            row.error = str(result.get("error"))[:2000]
            logger.error(f"[PurchasingBrief] generation failed: {row.error}")

        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def get_or_generate(
        self, db: Session, max_age_hours: int = DEFAULT_MAX_AGE_HOURS, **kwargs
    ) -> Optional[PurchasingBrief]:
        """Return a recent successful brief, or write a new one.

        Keeps the 4am workbook and the 7am digest on one brief (and one API
        call) while letting an on-demand run take a fresh read. Never raises —
        a brief is an enhancement to the report, not a precondition for it.
        """
        row = self.latest(db, successful_only=True)
        if row and row.generated_at and (
            datetime.utcnow() - row.generated_at
        ) <= timedelta(hours=max_age_hours):
            return row
        try:
            return self.generate(db, **kwargs)
        except Exception as e:
            logger.error(f"[PurchasingBrief] get_or_generate failed: {e}")
            return row  # stale is better than nothing

    def latest(self, db: Session, successful_only: bool = True) -> Optional[PurchasingBrief]:
        q = db.query(PurchasingBrief)
        if successful_only:
            q = q.filter(PurchasingBrief.brief_json.isnot(None))
        return q.order_by(PurchasingBrief.generated_at.desc()).first()

    # ── input gathering (best-effort) ───────────────────────────────────────

    def _gather_so_rows(self, req: dict, today: date) -> Optional[List[dict]]:
        try:
            from app.integrations.bc.client import bc_client
            from app.services.planning_workbook_service import build_so_rows
            return build_so_rows(req, bc_client.get_open_sales_orders_with_lines(), today=today)
        except Exception as e:
            logger.warning(f"[PurchasingBrief] sales-order RAG unavailable: {e}")
            return None

    def _gather_proposals(self, db: Session) -> Optional[List[dict]]:
        try:
            from app.services.cut_work_order_service import cut_work_order_service
            return cut_work_order_service.build_live_proposals(db)
        except Exception as e:
            logger.warning(f"[PurchasingBrief] cut proposals unavailable: {e}")
            return None

    # ── the model call ──────────────────────────────────────────────────────

    def _ask_claude(self, facts: dict, diff: dict) -> dict:
        from app.integrations.ai.client import ai_client

        if not ai_client.client:
            return {"success": False, "error": "AI client not initialized"}

        model = getattr(settings, "PURCHASING_BRIEF_MODEL", None) or BRIEF_MODEL
        user = (
            "TODAY'S FACTS:\n"
            f"{json.dumps(facts, indent=2, default=str)}\n\n"
            "CHANGE SINCE THE LAST BRIEF (already computed — do not recalculate):\n"
            f"{json.dumps(diff, indent=2, default=str)}\n\n"
            "Write today's brief."
        )

        try:
            response = ai_client.client.messages.create(
                model=model,
                max_tokens=8000,  # covers thinking + the brief itself
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
            )
            text = _response_text(response)
            brief = _parse_json_object(text)
            if not isinstance(brief, dict):
                return {"success": False, "error": "model did not return a JSON object"}
            return {
                "success": True,
                "brief": _normalize_brief(brief),
                "model": model,
                "input_tokens": getattr(response.usage, "input_tokens", None),
                "output_tokens": getattr(response.usage, "output_tokens", None),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── rendering ───────────────────────────────────────────────────────────

    def render_html(self, row: Optional[PurchasingBrief]) -> str:
        """The brief as an HTML block for the top of the digest email.

        Returns "" when there is no brief, so the caller can concatenate it
        unconditionally and the digest degrades to the plain tables.
        """
        if not row or not row.brief_json:
            return ""
        b = row.brief_json
        stamp = row.generated_at.strftime("%b %d, %H:%M UTC") if row.generated_at else ""

        def section(title, items, color="#111827"):
            items = [i for i in (items or []) if i]
            if not items:
                return ""
            lis = "".join(
                f"<li style='margin:3px 0'>{_esc(i)}</li>" for i in items
            )
            return (
                f"<div style='margin:10px 0 0'><div style='font-size:12px;font-weight:700;"
                f"text-transform:uppercase;letter-spacing:.04em;color:{color}'>{title}</div>"
                f"<ul style='margin:4px 0 0;padding-left:18px;font-size:13px;line-height:1.45'>{lis}</ul></div>"
            )

        decisions = ""
        if b.get("decisions"):
            rows = "".join(
                f"<li style='margin:3px 0'><b>{_esc(d.get('question'))}</b>"
                + (f" — {_esc(d.get('context'))}" if d.get("context") else "")
                + "</li>"
                for d in b["decisions"] if d.get("question")
            )
            if rows:
                decisions = (
                    "<div style='margin:10px 0 0'><div style='font-size:12px;font-weight:700;"
                    "text-transform:uppercase;letter-spacing:.04em;color:#b45309'>Needs your call</div>"
                    f"<ul style='margin:4px 0 0;padding-left:18px;font-size:13px;line-height:1.45'>{rows}</ul></div>"
                )

        return (
            "<div style='border:1px solid #e5e7eb;border-left:4px solid #2563eb;border-radius:8px;"
            "padding:14px 16px;margin:0 0 18px;background:#f9fafb'>"
            "<div style='font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.06em'>"
            f"Morning brief · {stamp}</div>"
            f"<div style='font-size:15px;font-weight:600;margin:6px 0 2px'>{_esc(b.get('headline'))}</div>"
            + section("Buy today", b.get("buy_today"), "#b91c1c")
            + section("At risk", b.get("at_risk"), "#b45309")
            + section("Changed since yesterday", b.get("changed"))
            + decisions
            + section("Watch", b.get("watch"), "#6b7280")
            + "</div>"
        )

    def summary_lines(self, row: Optional[PurchasingBrief]) -> List[tuple]:
        """The brief as (heading, text) rows for the workbook Summary tab."""
        if not row or not row.brief_json:
            return []
        b = row.brief_json
        out: List[tuple] = [("MORNING BRIEF", b.get("headline") or "")]
        for label, key in (
            ("Buy today", "buy_today"),
            ("At risk", "at_risk"),
            ("Changed", "changed"),
            ("Watch", "watch"),
        ):
            for i, line in enumerate(b.get(key) or []):
                out.append((label if i == 0 else "", str(line)))
        for i, d in enumerate(b.get("decisions") or []):
            q = d.get("question") or ""
            ctx = d.get("context") or ""
            out.append(("Needs your call" if i == 0 else "", f"{q} — {ctx}" if ctx else q))
        return out


# ── helpers ─────────────────────────────────────────────────────────────────

def _response_text(response) -> str:
    """First text block of a response.

    Not ``content[0].text``: on thinking-enabled models the first block is a
    thinking block, so index 0 is not the answer.
    """
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text or ""
    return ""


def _parse_json_object(text: str) -> Optional[dict]:
    """Parse the JSON object out of a model response, fenced or bare."""
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        start = t.find("```")
        fence_end = t.find("\n", start)
        end = t.find("```", fence_end if fence_end > 0 else start + 3)
        if fence_end > 0 and end > fence_end:
            t = t[fence_end + 1:end].strip()
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            return None
        t = t[start:end + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        logger.error(f"[PurchasingBrief] brief JSON parse failed: {e}")
        return None


def _normalize_brief(b: dict) -> dict:
    """Coerce the model's object into the shape the renderers expect."""
    def as_list(v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [x for x in v if x]

    decisions = []
    for d in as_list(b.get("decisions")):
        if isinstance(d, str):
            decisions.append({"question": d, "context": ""})
        elif isinstance(d, dict) and d.get("question"):
            decisions.append({
                "question": str(d["question"]),
                "context": str(d.get("context") or ""),
            })

    return {
        "headline": str(b.get("headline") or "").strip(),
        "buy_today": [str(x) for x in as_list(b.get("buy_today"))][:5],
        "at_risk": [str(x) for x in as_list(b.get("at_risk"))][:5],
        "changed": [str(x) for x in as_list(b.get("changed"))][:4],
        "decisions": decisions[:4],
        "watch": [str(x) for x in as_list(b.get("watch"))][:3],
    }


def _esc(s) -> str:
    """Escape model-authored text before it goes into the HTML email."""
    return (
        str(s or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


purchasing_brief_service = PurchasingBriefService()
