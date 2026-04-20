"""
Escalating Margin Service
=========================
Client-specific volume discount pricing. As quote value increases,
gross margin decreases along a piecewise-linear curve.

Currently configured for GNB Manitoba. The breakpoints define the
target GM% at specific "value at 30% GM" thresholds. Between
breakpoints, GM% is interpolated linearly.

Usage:
    from app.services.escalating_margin_service import get_escalating_margin

    profile = get_escalating_margin("GNB_MANITOBA")
    if profile:
        result = profile.calculate(total_value_at_30pct)
        # result = {"target_gm": 23.0, "multiplier": 0.909, "discount_pct": 9.1}
        # Apply: adjusted_price = line_price * result["multiplier"]
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MarginBreakpoint:
    """A single point on the escalating margin curve."""
    value_threshold: float  # Quote value at 30% GM that triggers this tier
    target_gm_pct: float   # Target gross margin % at this threshold


@dataclass
class EscalatingMarginProfile:
    """
    A named escalating margin profile with breakpoints.

    Breakpoints must be sorted by value_threshold ascending.
    Below the first breakpoint, base_gm applies (no discount).
    Above the last breakpoint, the last target_gm is the floor.
    """
    name: str
    customer_identifier: str  # BC customer name or ID to match
    base_gm_pct: float = 30.0  # The "standard" GM% these breakpoints are relative to
    breakpoints: List[MarginBreakpoint] = field(default_factory=list)

    def get_target_gm(self, total_value: float) -> float:
        """
        Get the target GM% for a given total quote value.
        Interpolates linearly between breakpoints.
        """
        if not self.breakpoints:
            return self.base_gm_pct

        # Below first breakpoint → base GM
        if total_value < self.breakpoints[0].value_threshold:
            return self.base_gm_pct

        # Above last breakpoint → floor GM
        if total_value >= self.breakpoints[-1].value_threshold:
            return self.breakpoints[-1].target_gm_pct

        # Find which segment we're in and interpolate
        for i in range(len(self.breakpoints) - 1):
            lo = self.breakpoints[i]
            hi = self.breakpoints[i + 1]
            if lo.value_threshold <= total_value < hi.value_threshold:
                # Linear interpolation
                t = (total_value - lo.value_threshold) / (hi.value_threshold - lo.value_threshold)
                return lo.target_gm_pct + t * (hi.target_gm_pct - lo.target_gm_pct)

        return self.breakpoints[-1].target_gm_pct

    def calculate(self, total_value: float) -> Dict:
        """
        Calculate the pricing adjustment for a given quote total.

        Args:
            total_value: Total quote value priced at the base GM%

        Returns:
            dict with:
                target_gm: The interpolated target GM%
                multiplier: Factor to multiply each line price by
                discount_pct: Percentage discount from base price
                adjusted_total: What the total becomes after applying
        """
        target_gm = self.get_target_gm(total_value)

        # Multiplier: ratio of cost-complement at new GM vs base GM
        # price_base = cost / (1 - base_gm)
        # price_new  = cost / (1 - target_gm)
        # multiplier = price_new / price_base = (1 - base_gm) / (1 - target_gm)
        if target_gm >= 100:
            multiplier = 0.0
        else:
            multiplier = (1 - self.base_gm_pct / 100) / (1 - target_gm / 100)

        discount_pct = round((1 - multiplier) * 100, 2)
        adjusted_total = round(total_value * multiplier, 2)

        logger.info(
            f"Escalating margin [{self.name}]: "
            f"${total_value:,.0f} → {target_gm:.1f}% GM "
            f"(multiplier={multiplier:.4f}, discount={discount_pct:.1f}%, "
            f"adjusted=${adjusted_total:,.0f})"
        )

        return {
            "profile_name": self.name,
            "total_at_base_gm": round(total_value, 2),
            "target_gm": round(target_gm, 2),
            "base_gm": self.base_gm_pct,
            "multiplier": round(multiplier, 6),
            "discount_pct": discount_pct,
            "adjusted_total": adjusted_total,
        }


# ============================================================================
# CONFIGURED PROFILES
# ============================================================================

ESCALATING_PROFILES: Dict[str, EscalatingMarginProfile] = {
    "GNB_MANITOBA": EscalatingMarginProfile(
        name="GNB Manitoba",
        customer_identifier="GNB",  # Matched against BC customer name (case-insensitive contains)
        base_gm_pct=30.0,
        breakpoints=[
            MarginBreakpoint(value_threshold=10_000, target_gm_pct=26.0),
            MarginBreakpoint(value_threshold=16_000, target_gm_pct=23.0),
            MarginBreakpoint(value_threshold=38_000, target_gm_pct=18.5),
            MarginBreakpoint(value_threshold=180_000, target_gm_pct=9.5),
        ],
    ),
}

# Customer name → profile key mapping (populated on first use)
_customer_cache: Dict[str, Optional[str]] = {}


def get_escalating_margin(customer_name: str) -> Optional[EscalatingMarginProfile]:
    """
    Look up an escalating margin profile by customer name.

    Args:
        customer_name: BC customer display name

    Returns:
        EscalatingMarginProfile if customer has one, None otherwise
    """
    if not customer_name:
        return None

    name_upper = customer_name.upper()

    # Check cache
    if name_upper in _customer_cache:
        key = _customer_cache[name_upper]
        return ESCALATING_PROFILES.get(key) if key else None

    # Search profiles
    for key, profile in ESCALATING_PROFILES.items():
        if profile.customer_identifier.upper() in name_upper:
            _customer_cache[name_upper] = key
            logger.info(f"Escalating margin profile matched: '{customer_name}' → {profile.name}")
            return profile

    _customer_cache[name_upper] = None
    return None


def get_profile_by_key(key: str) -> Optional[EscalatingMarginProfile]:
    """Get a profile by its config key (e.g. 'GNB_MANITOBA')."""
    return ESCALATING_PROFILES.get(key)


def list_profiles() -> List[Dict]:
    """List all configured escalating margin profiles."""
    result = []
    for key, profile in ESCALATING_PROFILES.items():
        result.append({
            "key": key,
            "name": profile.name,
            "customer_identifier": profile.customer_identifier,
            "base_gm_pct": profile.base_gm_pct,
            "breakpoints": [
                {"value": bp.value_threshold, "gm_pct": bp.target_gm_pct}
                for bp in profile.breakpoints
            ],
        })
    return result
