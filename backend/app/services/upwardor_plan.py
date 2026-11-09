"""Upwardor payable plan and the live reforecast.

The weekly baseline is the Nov 2026 schedule (statement opening balance
$831,405 on Nov 3, before that day's payment). Published week-end balances
are the source of truth for the static plan. A week that matches the plan
lands on those published ends.

Recognized variances shift every later week-end, including Christmas, by
the same dollars. They are counted once:

- A closed week uses actual invoices, payments, and credits where those
  figures are known. An unknown figure stays on the plan. It is not zero.
- An open week keeps the rest of its payment plan. Invoice catch-up is
  dropped when purchasing is already below the pace expected by now, so a
  light buying week improves the Christmas projection immediately.
- Future weeks keep the baseline unless a lever removes a planned flow
  (GNB moved to January, return credit missed).

Paying more than plan and buying less than plan is the ahead state. The
lower purchasing also lowers later invoice ceilings. Those ceilings are the
budget not to buy back. They are not subtracted from Christmas a second time.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

EDMONTON = timezone(timedelta(hours=-6))
TARGET = 500_000
OPENING_BALANCE = 831_405
GNB_PO_NUMBER = "PO-001066"
# The Nov 24 invoice plan includes this PO. Moving the whole amount to
# January is what takes the published ~$570K Christmas down to ~$493K.
GNB_INVOICE_AMOUNT = 77_035
GNB_WEEK = date(2026, 11, 24)
RETURN_CREDIT = 60_000
RETURN_OFFSET = 19_901
DEC_BUY_CAP = 7_500
RECENT_WEEKLY_BUY = 32_600
TOLERANCE = 1
PACE_MIN_ELAPSED = 1 / 7
PLAN_START = date(2026, 11, 3)

# week_of, collections, return credit, offset, payments, invoices, plan end, status-quo end
_PLAN_ROWS = (
    (date(2026, 11, 3), 60617, 0, 0, 70431, 90664, 851639, 909922),
    (date(2026, 11, 10), 99324, 0, 0, 82336, 31298, 800601, 915684),
    (date(2026, 11, 17), 27002, 0, 0, 317, 17981, 818265, 903665),
    (date(2026, 11, 24), 68577, 60000, 19901, 51589, 77035, 763810, 950700),
    (date(2026, 12, 1), 118928, 0, 0, 92244, 7500, 679067, 953300),
    (date(2026, 12, 8), 57500, 0, 0, 46979, 7500, 639588, 955900),
    (date(2026, 12, 15), 57500, 0, 0, 37282, 7500, 609806, 958500),
    (date(2026, 12, 22), 57500, 0, 0, 46979, 7500, 570328, 961100),
)

PLAN_WEEKS = tuple(
    {
        "week_of": row[0],
        "collections": row[1],
        "return_credit": row[2],
        "offset": row[3],
        "payments": row[4],
        "invoices": row[5],
        "credits": row[2] + row[3],
        "plan_end": row[6],
        "status_quo_end": row[7],
        "dec_buy_cap": row[0].month == 12,
    }
    for row in _PLAN_ROWS
)
PLAN_BY_WEEK = {week["week_of"]: week for week in PLAN_WEEKS}
PLAN_CHRISTMAS = PLAN_WEEKS[-1]["plan_end"]
STATUS_QUO_CHRISTMAS = PLAN_WEEKS[-1]["status_quo_end"]
PLAN_PAYMENTS_TOTAL = sum(week["payments"] for week in PLAN_WEEKS)
PLAN_INVOICES_TOTAL = sum(week["invoices"] for week in PLAN_WEEKS)

LEVER_IDS = ("return_credit", "gnb_january", "stock_po_holds", "dec_buy_cap")
RETURN_CREDIT_STATUSES = ("planned", "posted", "missed")
GNB_STATUSES = ("in_plan", "moved")
STOCK_STATUSES = ("not_started", "holding", "released")


def money(value: float) -> int:
    """Nearest dollar. Plan figures are whole dollars."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def as_edmonton(moment: Optional[datetime] = None) -> datetime:
    """Report clock. Alberta did not fall back in 2026, so the offset stays UTC-6."""
    if moment is None:
        return datetime.now(EDMONTON)
    if isinstance(moment, date) and not isinstance(moment, datetime):
        return datetime(moment.year, moment.month, moment.day, 12, 0, tzinfo=EDMONTON)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=EDMONTON)
    return moment.astimezone(EDMONTON)


def week_state(week_of: date, moment: datetime) -> str:
    start = datetime(week_of.year, week_of.month, week_of.day, tzinfo=EDMONTON)
    end = start + timedelta(days=7)
    if moment < start:
        return "future"
    if moment >= end:
        return "closed"
    return "open"


def week_elapsed(week_of: date, moment: datetime) -> float:
    start = datetime(week_of.year, week_of.month, week_of.day, tzinfo=EDMONTON)
    elapsed = (moment - start).total_seconds() / timedelta(days=7).total_seconds()
    if elapsed < 0:
        return 0.0
    if elapsed > 1:
        return 1.0
    return elapsed


def week_label(week_of: date) -> str:
    return f"{week_of.strftime('%b')} {week_of.day}"


def _blank_actual() -> dict[str, Any]:
    return {
        "invoices": None,
        "payments": None,
        "credits": None,
        "invoices_source": "unavailable",
        "payments_source": "unavailable",
        "credits_source": "unavailable",
    }


def merge_actuals(
    bc_weeks: Optional[dict[str, dict]],
    overrides: Optional[dict],
    *,
    balance: Optional[float],
    as_of: datetime,
) -> dict[str, dict]:
    """Staff numbers cover a missing Business Central figure. Unknown stays unknown.

    When the vendor balance is live and exactly one week has started, payments
    for that week are implied by the balance identity if the ledger did not
    return them. The live balance already includes those payments, so the
    displayed balance stays equal to it. Later weeks are not guessed apart.
    """
    saved = (overrides or {}).get("weeks") or {}
    bc_weeks = bc_weeks or {}
    merged: dict[str, dict] = {}
    for week in PLAN_WEEKS:
        key = week["week_of"].isoformat()
        base = _blank_actual()
        incoming = bc_weeks.get(key) or {}
        for field in ("invoices", "payments", "credits"):
            if incoming.get(field) is not None:
                base[field] = money(incoming[field])
                base[f"{field}_source"] = incoming.get(f"{field}_source") or "business_central"
        staff = saved.get(key) or {}
        for field in ("invoices", "payments", "credits"):
            if field in staff and staff[field] is not None:
                base[field] = money(staff[field])
                base[f"{field}_source"] = "staff_override"
        merged[key] = base

    _derive_open_week_payments(merged, balance=balance, as_of=as_of)
    return merged


def _derive_open_week_payments(merged: dict[str, dict], *, balance: Optional[float], as_of: datetime) -> None:
    if balance is None:
        return
    started = [week for week in PLAN_WEEKS if week_state(week["week_of"], as_of) != "future"]
    if len(started) != 1:
        return
    week = started[0]
    row = merged[week["week_of"].isoformat()]
    if row["payments"] is not None:
        return
    if row["invoices"] is None:
        return
    credits = row["credits"] if row["credits"] is not None else 0
    # The first week's plan has no credit. Don't invent a payment once a
    # credit is part of the identity and we have not seen it.
    if week["credits"] and row["credits"] is None:
        return
    # live balance = opening + invoices - credits - payments.
    # Payments are solved once. They are not subtracted from the live balance.
    implied = OPENING_BALANCE + row["invoices"] - credits - money(balance)
    if implied < -TOLERANCE:
        return
    row["payments"] = max(0, money(implied))
    row["payments_source"] = "derived_from_balance"


def resolve_lever_choices(
    overrides: Optional[dict],
    purchase_orders: Optional[list[dict]],
    actuals: dict[str, dict],
    as_of: datetime,
) -> dict[str, dict]:
    """Admin choice wins. Otherwise read the PO date and posted credits."""
    saved = (overrides or {}).get("levers") or {}
    notes = {key: (saved.get(key) or {}).get("note") or "" for key in LEVER_IDS}

    gnb_admin = (saved.get("gnb_january") or {}).get("status")
    if gnb_admin in GNB_STATUSES:
        gnb = {"status": gnb_admin, "source": "staff", "note": notes["gnb_january"]}
    else:
        gnb = _gnb_from_pos(purchase_orders)
        gnb["note"] = notes["gnb_january"]

    credit_admin = (saved.get("return_credit") or {}).get("status")
    if credit_admin in RETURN_CREDIT_STATUSES:
        credit = {"status": credit_admin, "source": "staff", "note": notes["return_credit"]}
    else:
        credit = _credit_from_actuals(actuals, as_of)
        credit["note"] = notes["return_credit"]

    stock_admin = (saved.get("stock_po_holds") or {}).get("status")
    if stock_admin in STOCK_STATUSES:
        stock = {"status": stock_admin, "source": "staff", "note": notes["stock_po_holds"]}
    else:
        stock = {"status": "not_started", "source": "baseline", "note": notes["stock_po_holds"]}

    return {
        "gnb_january": gnb,
        "return_credit": credit,
        "stock_po_holds": stock,
        "dec_buy_cap_note": notes["dec_buy_cap"],
    }


def _gnb_from_pos(purchase_orders: Optional[list[dict]]) -> dict[str, str]:
    for po in purchase_orders or []:
        number = str(po.get("number") or "")
        if number != GNB_PO_NUMBER:
            continue
        raw = po.get("requested_receipt_date") or ""
        try:
            receipt = date.fromisoformat(str(raw)[:10])
        except ValueError:
            return {"status": "in_plan", "source": "business_central"}
        if receipt >= date(2027, 1, 1):
            return {"status": "moved", "source": "business_central"}
        return {"status": "in_plan", "source": "business_central"}
    return {"status": "in_plan", "source": "baseline"}


def _credit_from_actuals(actuals: dict[str, dict], as_of: datetime) -> dict[str, str]:
    posted = 0
    saw_closed_actual = False
    for week in PLAN_WEEKS:
        row = actuals.get(week["week_of"].isoformat()) or {}
        credits = row.get("credits")
        if credits is None:
            continue
        posted += credits
        if week_state(week["week_of"], as_of) == "closed":
            saw_closed_actual = True
    if posted >= RETURN_CREDIT:
        return {"status": "posted", "source": "actuals"}
    nov = week_state(GNB_WEEK, as_of)
    nov_credits = (actuals.get(GNB_WEEK.isoformat()) or {}).get("credits")
    if nov == "closed" and nov_credits is not None and nov_credits < RETURN_CREDIT and saw_closed_actual:
        return {"status": "missed", "source": "actuals"}
    return {"status": "planned", "source": "baseline"}


def _forecast_amount(planned: int, actual: Optional[int], state: str, elapsed: float, *, pace: bool) -> tuple[int, int]:
    """Return (forecast total for the week, pace shortfall removed from the remainder)."""
    if state == "future" or actual is None:
        return planned, 0
    if state == "closed":
        return actual, 0
    if pace and elapsed >= PACE_MIN_ELAPSED and actual < (planned * elapsed) - 0.5:
        shortfall = (planned * elapsed) - actual
        remaining = max(0.0, planned - actual - shortfall)
        return money(actual + remaining), money(shortfall)
    remaining = max(0, planned - actual)
    return actual + remaining, 0


def build_forecast(
    as_of: datetime,
    actuals: dict[str, dict],
    levers: dict[str, dict],
    *,
    balance: Optional[float] = None,
    balance_source: str = "unavailable",
    balance_as_of: Optional[str] = None,
    purchase_orders: Optional[list[dict]] = None,
    errors: Optional[list[str]] = None,
) -> dict[str, Any]:
    moment = as_edmonton(as_of)
    gnb_status = (levers.get("gnb_january") or {}).get("status") or "in_plan"
    credit_status = (levers.get("return_credit") or {}).get("status") or "planned"
    gnb_moved = gnb_status == "moved"
    credit_missed = credit_status == "missed"

    cumulative = 0
    closed_underspend = 0
    invoice_delta = 0
    payment_delta = 0
    invoice_compared = False
    payment_compared = False
    rows: list[dict[str, Any]] = []

    for week in PLAN_WEEKS:
        key = week["week_of"].isoformat()
        actual = actuals.get(key) or _blank_actual()
        state = week_state(week["week_of"], moment)
        elapsed = week_elapsed(week["week_of"], moment) if state == "open" else (1.0 if state == "closed" else 0.0)

        effective_invoices = week["invoices"]
        effective_credits = week["credits"]
        gnb_applied = False
        credit_removed = False
        actual_invoices = actual.get("invoices")
        if (
            gnb_moved
            and week["week_of"] == GNB_WEEK
            and not (state == "closed" and actual_invoices is not None)
        ):
            effective_invoices = max(0, week["invoices"] - GNB_INVOICE_AMOUNT)
            gnb_applied = True
        if credit_missed and week["week_of"] == GNB_WEEK and not (
            state == "closed" and actual.get("credits") is not None
        ):
            effective_credits = max(0, week["credits"] - RETURN_CREDIT)
            credit_removed = True

        invoice_forecast, pace_shortfall = _forecast_amount(
            effective_invoices, actual_invoices, state, elapsed, pace=True
        )
        payment_forecast, _ = _forecast_amount(
            week["payments"], actual.get("payments"), state, elapsed, pace=False
        )
        credit_forecast, _ = _forecast_amount(
            effective_credits, actual.get("credits"), state, elapsed, pace=False
        )
        variance = money(
            (invoice_forecast - week["invoices"])
            - (payment_forecast - week["payments"])
            - (credit_forecast - week["credits"])
        )
        cumulative += variance

        if state == "closed" and actual_invoices is not None:
            closed_underspend += max(0, week["invoices"] - actual_invoices)

        if state != "future":
            if actual_invoices is not None and (state == "closed" or elapsed >= PACE_MIN_ELAPSED):
                invoice_compared = True
                expected = week["invoices"] if state == "closed" else week["invoices"] * elapsed
                invoice_delta += actual_invoices - expected
            elif state == "open" and actual_invoices is not None and actual_invoices > week["invoices"]:
                invoice_compared = True
                invoice_delta += actual_invoices - week["invoices"]
            payments = actual.get("payments")
            if payments is not None and (state == "closed" or elapsed >= PACE_MIN_ELAPSED):
                payment_compared = True
                expected_pay = week["payments"] if state == "closed" else week["payments"] * elapsed
                payment_delta += payments - expected_pay
            elif state == "open" and payments is not None and payments > week["payments"]:
                payment_compared = True
                payment_delta += payments - week["payments"]

        hit = "upcoming"
        if state == "open":
            hit = "in_progress"
        elif state == "closed":
            known = actual_invoices is not None or actual.get("payments") is not None
            if not known:
                hit = "pending"
            elif variance > TOLERANCE:
                hit = "miss"
            elif variance < -TOLERANCE:
                hit = "ahead"
            else:
                hit = "hit"

        rows.append({
            "week_of": key,
            "label": week_label(week["week_of"]),
            "state": state,
            "elapsed": round(elapsed, 4),
            "collections": week["collections"],
            "planned_invoices": week["invoices"],
            "effective_planned_invoices": effective_invoices,
            "actual_invoices": actual_invoices,
            "invoice_forecast": invoice_forecast,
            "invoice_source": actual.get("invoices_source") or "unavailable",
            "pace_shortfall": pace_shortfall,
            "planned_payments": week["payments"],
            "actual_payments": actual.get("payments"),
            "payment_forecast": payment_forecast,
            "payment_source": actual.get("payments_source") or "unavailable",
            "planned_credits": week["credits"],
            "return_credit": week["return_credit"],
            "offset": week["offset"],
            "actual_credits": actual.get("credits"),
            "credit_forecast": credit_forecast,
            "credit_source": actual.get("credits_source") or "unavailable",
            "plan_end": week["plan_end"],
            "status_quo_end": week["status_quo_end"],
            "variance": variance,
            "live_end": week["plan_end"] + cumulative,
            "hit": hit,
            "gnb_applied": gnb_applied,
            "credit_removed": credit_removed,
            "dec_buy_cap": week["dec_buy_cap"],
            "has_actual": any(actual.get(field) is not None for field in ("invoices", "payments", "credits")),
        })

    cut_left = closed_underspend
    invoice_target_reduction = 0
    for row in rows:
        if row["state"] == "closed":
            row["adjusted_invoice_target"] = row["invoice_forecast"]
            row["target_auto_reduced"] = False
            continue
        base = row["invoice_forecast"] if row["state"] == "open" else row["effective_planned_invoices"]
        cut = min(base, cut_left)
        row["adjusted_invoice_target"] = base - cut
        row["target_auto_reduced"] = cut > 0 or row["pace_shortfall"] > 0 or row["gnb_applied"]
        cut_left -= cut
        invoice_target_reduction += cut

    live_christmas = rows[-1]["live_end"]
    favorable = sum(max(0, -row["variance"]) for row in rows)
    stretch = PLAN_CHRISTMAS - favorable
    bought_less = invoice_compared and invoice_delta < -TOLERANCE
    paid_more = payment_compared and payment_delta > TOLERANCE
    if live_christmas > PLAN_CHRISTMAS + TOLERANCE:
        status = "behind"
    elif (bought_less and paid_more) or live_christmas < PLAN_CHRISTMAS - TOLERANCE:
        status = "ahead"
    else:
        status = "on_track"

    current, current_source = _current_balance(rows, balance, balance_source)
    open_row = next((row for row in rows if row["state"] == "open"), None)
    if open_row is None:
        open_row = rows[-1] if moment >= datetime(PLAN_WEEKS[-1]["week_of"].year, PLAN_WEEKS[-1]["week_of"].month, PLAN_WEEKS[-1]["week_of"].day, tzinfo=EDMONTON) + timedelta(days=7) else rows[0]

    dec_status, dec_detail = _dec_buy_cap(rows)
    levers_out = _lever_payload(levers, dec_status, dec_detail, gnb_moved, credit_missed)

    return {
        "as_of": moment.isoformat(),
        "timezone": "America/Edmonton (UTC-6, no fall-back in 2026)",
        "opening_balance": OPENING_BALANCE,
        "opening_note": "Upwardor statement on Nov 3, 2026, before that day's payment.",
        "target": TARGET,
        "current_balance": current,
        "current_balance_source": current_source,
        "balance_as_of": balance_as_of if current_source == "business_central" else None,
        "gap_to_target": current - TARGET,
        "plan_christmas": PLAN_CHRISTMAS,
        "live_christmas": live_christmas,
        "stretch_christmas": stretch,
        "status_quo_christmas": STATUS_QUO_CHRISTMAS,
        "gnb_christmas": PLAN_CHRISTMAS - GNB_INVOICE_AMOUNT,
        "status": status,
        "status_vs_target": "under" if live_christmas <= TARGET else "above",
        "bought_less_than_plan": bought_less,
        "paid_more_than_plan": paid_more,
        "ahead_on_both": bought_less and paid_more,
        "invoice_delta": money(invoice_delta) if invoice_compared else None,
        "payment_delta": money(payment_delta) if payment_compared else None,
        "targets_auto_reduced": invoice_target_reduction > 0,
        "invoice_target_reduction": invoice_target_reduction,
        "plan_payments_total": PLAN_PAYMENTS_TOTAL,
        "plan_invoices_total": PLAN_INVOICES_TOTAL,
        "this_week": _this_week(open_row),
        "weeks": [_public_week(row) for row in rows],
        "chart": [_chart_point(row, current, current_source) for row in rows],
        "levers": levers_out,
        "purchase_orders": [_public_po(po) for po in (purchase_orders or [])],
        "reforecast_note": _reforecast_note(
            status=status,
            bought_less=bought_less,
            paid_more=paid_more,
            invoice_delta=money(invoice_delta) if invoice_compared else 0,
            payment_delta=money(payment_delta) if payment_compared else 0,
            reduction=invoice_target_reduction,
            live_christmas=live_christmas,
            gnb_moved=gnb_moved,
            credit_missed=credit_missed,
        ),
        "sources": _sources(rows, current_source, errors or []),
    }


def _current_balance(rows: list[dict], balance: Optional[float], balance_source: str) -> tuple[int, str]:
    if balance is not None:
        return money(balance), balance_source or "business_central"
    started = [row for row in rows if row["state"] != "future"]
    if not any(row["has_actual"] for row in started):
        return OPENING_BALANCE, "statement_nov_3"
    running = OPENING_BALANCE
    for index, row in enumerate(started):
        previous_end = OPENING_BALANCE if index == 0 else rows[index - 1]["live_end"]
        if row["state"] == "closed":
            running = row["live_end"]
            continue
        inv = row["actual_invoices"] or 0
        pay = row["actual_payments"] or 0
        cred = row["actual_credits"] or 0
        running = previous_end + inv - pay - cred
    return money(running), "week_actuals"


def _dec_buy_cap(rows: list[dict]) -> tuple[str, str]:
    december = [row for row in rows if row["dec_buy_cap"]]
    known = [row for row in december if row["actual_invoices"] is not None and row["state"] != "future"]
    if any((row["actual_invoices"] or 0) > DEC_BUY_CAP for row in known):
        over = [row for row in known if (row["actual_invoices"] or 0) > DEC_BUY_CAP]
        names = ", ".join(row["label"] for row in over)
        return "over_cap", f"Invoices in {names} are over the ${DEC_BUY_CAP:,} weekly cap."
    if known:
        return "on_cap", f"December weeks with invoices posted are within ${DEC_BUY_CAP:,}."
    return "upcoming", (
        f"Plan cap is ${DEC_BUY_CAP:,} a week for Dec 1, Dec 8, Dec 15, and Dec 22. "
        f"Recent buying was about ${RECENT_WEEKLY_BUY:,} a week."
    )


def _lever_payload(levers, dec_status, dec_detail, gnb_moved, credit_missed) -> list[dict]:
    gnb = levers.get("gnb_january") or {}
    credit = levers.get("return_credit") or {}
    stock = levers.get("stock_po_holds") or {}
    gnb_effect = PLAN_CHRISTMAS - GNB_INVOICE_AMOUNT
    return [
        {
            "id": "return_credit",
            "title": "Return credit",
            "detail": (
                f"${RETURN_CREDIT:,} credit and ${RETURN_OFFSET:,} offset in the week of Nov 24. "
                + ("The forecast is holding the credit out." if credit_missed else "The forecast still includes both.")
            ),
            "status": credit.get("status") or "planned",
            "source": credit.get("source") or "baseline",
            "note": credit.get("note") or "",
            "options": [
                {"value": "planned", "label": "Planned"},
                {"value": "posted", "label": "Posted"},
                {"value": "missed", "label": "Missed"},
            ],
        },
        {
            "id": "gnb_january",
            "title": "GNB PO-001066 to January",
            "detail": (
                f"The Nov 24 invoice plan of ${GNB_INVOICE_AMOUNT:,} is this PO. "
                f"Moving it to January puts Christmas near ${gnb_effect:,}."
                + (" That move is in the live projection." if gnb_moved else " The baseline still keeps it in November.")
            ),
            "status": gnb.get("status") or "in_plan",
            "source": gnb.get("source") or "baseline",
            "note": gnb.get("note") or "",
            "options": [
                {"value": "in_plan", "label": "In the Nov 24 plan"},
                {"value": "moved", "label": "Moved to January"},
            ],
        },
        {
            "id": "stock_po_holds",
            "title": "Stock PO holds",
            "detail": "Hold Upwardor stock POs that are not needed to ship before Christmas.",
            "status": stock.get("status") or "not_started",
            "source": stock.get("source") or "baseline",
            "note": stock.get("note") or "",
            "options": [
                {"value": "not_started", "label": "Not started"},
                {"value": "holding", "label": "Holding"},
                {"value": "released", "label": "Released"},
            ],
        },
        {
            "id": "dec_buy_cap",
            "title": "December buy cap",
            "detail": dec_detail,
            "status": dec_status,
            "source": "actuals" if dec_status != "upcoming" else "baseline",
            "note": levers.get("dec_buy_cap_note") or "",
            "options": [],
        },
    ]


def _this_week(row: dict) -> dict:
    actual_invoices = row["actual_invoices"]
    actual_payments = row["actual_payments"]
    remaining_invoices = None if actual_invoices is None else max(0, row["invoice_forecast"] - actual_invoices)
    remaining_payments = None if actual_payments is None else max(0, row["payment_forecast"] - actual_payments)
    return {
        "week_of": row["week_of"],
        "label": row["label"],
        "state": row["state"],
        "planned_invoices": row["planned_invoices"],
        "actual_invoices": actual_invoices,
        "invoice_forecast": row["invoice_forecast"],
        "remaining_invoices": remaining_invoices,
        "invoice_variance": None if actual_invoices is None else actual_invoices - row["planned_invoices"],
        "pace_shortfall": row["pace_shortfall"],
        "planned_payments": row["planned_payments"],
        "actual_payments": actual_payments,
        "payment_forecast": row["payment_forecast"],
        "remaining_payments": remaining_payments,
        "payment_variance": None if actual_payments is None else actual_payments - row["planned_payments"],
        "variance": row["variance"],
        "hit": row["hit"],
        "invoice_source": row["invoice_source"],
        "payment_source": row["payment_source"],
        "target_reduced": row["pace_shortfall"] > 0,
        "adjusted_invoice_target": row["adjusted_invoice_target"],
    }


def _public_week(row: dict) -> dict:
    invoice_delta = None if row["actual_invoices"] is None else row["actual_invoices"] - row["planned_invoices"]
    payment_delta = None if row["actual_payments"] is None else row["actual_payments"] - row["planned_payments"]
    return {
        "week_of": row["week_of"],
        "label": row["label"],
        "state": row["state"],
        "collections": row["collections"],
        "planned_invoices": row["planned_invoices"],
        "actual_invoices": row["actual_invoices"],
        "invoice_delta": invoice_delta,
        "invoice_forecast": row["invoice_forecast"],
        "adjusted_invoice_target": row["adjusted_invoice_target"],
        "target_auto_reduced": row["target_auto_reduced"],
        "planned_payments": row["planned_payments"],
        "actual_payments": row["actual_payments"],
        "payment_delta": payment_delta,
        "planned_credits": row["planned_credits"],
        "actual_credits": row["actual_credits"],
        "plan_end": row["plan_end"],
        "status_quo_end": row["status_quo_end"],
        "live_end": row["live_end"],
        "variance": row["variance"],
        "hit": row["hit"],
        "invoice_source": row["invoice_source"],
        "payment_source": row["payment_source"],
        "credit_source": row["credit_source"],
    }


def _chart_point(row: dict, current: int, current_source: str) -> dict:
    actual = None
    if row["state"] == "closed" and row["has_actual"]:
        actual = row["live_end"]
    elif row["state"] == "open":
        actual = current
    return {
        "week": row["label"],
        "week_of": row["week_of"],
        "plan": row["plan_end"],
        "status_quo": row["status_quo_end"],
        "live": row["live_end"],
        "actual": actual,
        "target": TARGET,
    }


def _reforecast_note(
    *,
    status: str,
    bought_less: bool,
    paid_more: bool,
    invoice_delta: int,
    payment_delta: int,
    reduction: int,
    live_christmas: int,
    gnb_moved: bool,
    credit_missed: bool,
) -> str:
    parts = []
    if bought_less and paid_more:
        parts.append(
            f"Ahead of plan: payments are ${payment_delta:,} higher than the pace we expected "
            f"and purchasing is ${abs(invoice_delta):,} lower."
        )
    elif status == "behind":
        parts.append(f"Christmas projection is ${live_christmas - PLAN_CHRISTMAS:,} over the static plan.")
    elif status == "ahead":
        parts.append(f"Christmas projection is ${PLAN_CHRISTMAS - live_christmas:,} under the static plan.")
    else:
        parts.append("Christmas projection is on the static plan.")
    if reduction > 0:
        parts.append(
            f"Invoice targets still ahead were reduced by ${reduction:,}. "
            "That underspend is already in the Christmas projection, so it is not subtracted again."
        )
    if gnb_moved:
        parts.append(f"GNB PO-001066 is treated as a January receipt, which removes ${GNB_INVOICE_AMOUNT:,} before Christmas.")
    if credit_missed:
        parts.append(f"The ${RETURN_CREDIT:,} return credit is marked missed, so the forecast no longer counts it.")
    return " ".join(parts)


def _sources(rows: list[dict], balance_source: str, errors: list[str]) -> dict:
    def rollup(field: str) -> str:
        values = {row[field] for row in rows if row["state"] != "future"}
        values.discard("unavailable")
        if not values:
            return "unavailable"
        if len(values) == 1:
            return next(iter(values))
        return "mixed"

    payment_source = rollup("payment_source")
    notes = []
    if payment_source == "unavailable":
        notes.append(
            "Weekly payments are not on the standard Business Central purchase-invoice feed. "
            "The week table keeps the payment plan until the vendor ledger is readable or an admin records the week."
        )
    elif payment_source == "derived_from_balance":
        notes.append(
            "Payments this week are the opening balance plus invoices minus the live vendor balance. "
            "That balance already includes those payments, so they are not subtracted again."
        )
    if balance_source == "statement_nov_3":
        notes.append(
            "Vendor balance is the Nov 3 statement opening because Business Central "
            "did not return the Upwardor balance."
        )
    return {
        "balance": balance_source,
        "invoices": rollup("invoice_source"),
        "payments": payment_source,
        "credits": rollup("credit_source"),
        "plan": "baseline_nov_2026",
        "notes": notes,
        "errors": errors,
    }


__all__ = [
    "DEC_BUY_CAP",
    "EDMONTON",
    "GNB_INVOICE_AMOUNT",
    "GNB_PO_NUMBER",
    "OPENING_BALANCE",
    "PLAN_CHRISTMAS",
    "PLAN_WEEKS",
    "TARGET",
    "build_forecast",
    "merge_actuals",
    "resolve_lever_choices",
    "week_state",
]
