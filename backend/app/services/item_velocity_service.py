"""Item velocity — how fast stock actually moves, for the 12-month goal of
holding only 3-month-consumable inventory.

Cutting a long stick down is most valuable when the donor is SLOW-moving: a
32'4" that has sat for months is dead capital, and turning it into pieces a job
needs today is exactly the inventory reduction Joey wants. So each cut proposal
is annotated with its donor's velocity, and the ones that clear slow stock are
flagged and float up the queue.

"Movement" is real outflow — Consumption (into production), Sale, and cuts
tagged CUT-* — NOT count/correction adjustments (ANNUAL_COUNT, COST CORR, …),
which are inventory noise, not consumption. months_supply = on_hand / monthly
rate: at/under 3 the item is highly consumable (the target state).

CRITICAL (Joey, 2026-07-20): a BULK cut-stock item is almost never consumed
directly — it is bought to be CUT DOWN into other sizes, and historically those
cuts are untagged adjustments the ledger can't distinguish from counts. So its
direct-outflow rate reads near zero and it looks dead when it is actually one of
the fastest-turning items — replenished every ~3 months. The tell is
REPURCHASING: an item bought on a healthy cadence is turning regardless of how
its consumption is recorded. So is_slow requires BOTH low outflow AND stale
purchasing; a recently-replenished item is never flagged slow. As cuts start
posting as CUT-* work orders, outflow will capture cutting directly too.
"""

import logging
from datetime import date, datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Entry types that count as real outflow.
_MOVEMENT_TYPES = {"Sale", "Consumption"}
# BC serialises the enum with x-escapes; match on a normalised form too.
_MOVEMENT_NORMALISED = {"sale", "consumption"}

SLOW_MONTHS_SUPPLY = 3.0   # Joey's target: hold only ~3 months of stock
STALE_DAYS = 90            # no real movement in a quarter = slow
# Bought within this window = actively replenished = turning (Joey replenishes
# bulk cut-stock every ~3 months; 120d gives that cadence a month of buffer).
REPLENISH_DAYS = 120


def _norm_entry_type(raw: str) -> str:
    """Normalise BC's escaped entry-type string, e.g.
    'Negative_x0020_Adjmt_x002E_' -> 'negative adjmt.'"""
    if not raw:
        return ""
    s = raw.replace("_x0020_", " ").replace("_x002E_", ".").replace("_x0027_", "'")
    return s.strip().lower()


def _is_movement(entry_type_raw: str, document_no: str) -> bool:
    et = _norm_entry_type(entry_type_raw)
    if et in _MOVEMENT_NORMALISED:
        return True
    # A tagged cut is real movement too, once cuts start posting as CUT-*.
    if et.startswith("negative adjmt") and (document_no or "").upper().startswith("CUT"):
        return True
    return False


class ItemVelocityService:
    def __init__(self):
        self._cache: Dict[str, tuple] = {}   # sku -> (expires_at_epoch, value)

    def donor_velocity(
        self,
        on_hand_by_sku: Dict[str, float],
        months: int = 12,
        today: Optional[date] = None,
    ) -> Dict[str, dict]:
        """Per-SKU velocity keyed by donor SKU.

        Returns {sku: {monthly_rate, months_supply, last_movement, days_since_movement,
        is_slow, sample}}. Best-effort: a SKU whose ledger can't be read comes
        back with monthly_rate 0 and is_slow True (no evidence it moves).
        """
        from app.integrations.bc.client import bc_client

        today = today or date.today()
        out: Dict[str, dict] = {}
        for sku, on_hand in on_hand_by_sku.items():
            try:
                out[sku] = self._one(bc_client, sku, float(on_hand or 0), months, today)
            except Exception as e:
                logger.warning(f"velocity: {sku} failed ({e}) — treating as slow")
                out[sku] = self._slow_default(on_hand)
        return out

    def _one(self, bc_client, sku, on_hand, months, today) -> dict:
        company_id = bc_client.company_id
        resp = bc_client._make_request(
            "GET",
            f"companies({company_id})/itemLedgerEntries?$filter=itemNumber eq '{sku}'"
            f"&$orderby=postingDate desc&$top=500",
        )
        entries = resp.get("value", [])

        cutoff = date(today.year - (months // 12), today.month, 1) if months >= 12 else today
        # Simpler trailing window: months back from today.
        cutoff = self._months_ago(today, months)

        consumed = 0.0
        last_movement: Optional[date] = None
        last_purchase: Optional[date] = None
        purchases = 0
        sample = 0
        for e in entries:
            pd = self._parse_date(e.get("postingDate"))
            if pd is None:
                continue
            et = _norm_entry_type(e.get("entryType"))
            if _is_movement(e.get("entryType"), e.get("documentNumber")):
                if last_movement is None or pd > last_movement:
                    last_movement = pd
                if pd >= cutoff:
                    consumed += abs(float(e.get("quantity") or 0))
                    sample += 1
            elif et == "purchase":
                if last_purchase is None or pd > last_purchase:
                    last_purchase = pd
                if pd >= cutoff:
                    purchases += 1

        monthly_rate = round(consumed / months, 3) if months else 0.0
        months_supply = round(on_hand / monthly_rate, 1) if monthly_rate > 0 else None
        days_since = (today - last_movement).days if last_movement else None
        days_since_purchase = (today - last_purchase).days if last_purchase else None

        # Actively repurchased = turning, even if its consumption is recorded as
        # cuts the ledger can't see (the bulk-cut-stock case).
        recently_replenished = days_since_purchase is not None and days_since_purchase <= REPLENISH_DAYS

        outflow_slow = (
            monthly_rate == 0
            or (months_supply is not None and months_supply > SLOW_MONTHS_SUPPLY)
            or (days_since is not None and days_since > STALE_DAYS)
        )
        is_slow = outflow_slow and not recently_replenished
        return {
            "monthly_rate": monthly_rate,
            "months_supply": months_supply,
            "last_movement": last_movement.isoformat() if last_movement else None,
            "days_since_movement": days_since,
            "last_purchase": last_purchase.isoformat() if last_purchase else None,
            "days_since_purchase": days_since_purchase,
            "purchases_12mo": purchases,
            "recently_replenished": bool(recently_replenished),
            "is_slow": bool(is_slow),
            "sample": sample,
        }

    @staticmethod
    def _slow_default(on_hand) -> dict:
        return {"monthly_rate": 0.0, "months_supply": None, "last_movement": None,
                "days_since_movement": None, "last_purchase": None,
                "days_since_purchase": None, "purchases_12mo": 0,
                "recently_replenished": False, "is_slow": True, "sample": 0}

    @staticmethod
    def _months_ago(d: date, months: int) -> date:
        m = d.month - 1 - months
        year = d.year + m // 12
        month = m % 12 + 1
        return date(year, month, 1)

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            return None


item_velocity_service = ItemVelocityService()
