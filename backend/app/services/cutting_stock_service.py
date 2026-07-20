"""Cutting-stock analysis — "can we satisfy this shortfall by cutting something
we already have, instead of buying it?"

A 1D cutting-stock (bin-packing) pass over the purchasing demand engine's
output. For each short item it looks for a LONGER SKU in the same cut family
that is sitting in stock, and works out how many donor sticks would be needed
and how much drop that leaves.

Deliberately read-only in this phase: it annotates rows, it does not reduce
``net_need``. Every recommendation carries the evidence behind it (donor SKU,
its on-hand, the exact cut list, the resulting waste) so a human can check it
against the rack before it is ever allowed to suppress a purchase.

WHY IT DOES NOT AUTO-SUPPRESS
    BC on-hand is known to be under-recorded (``inventory`` reads 0 on a large
    share of items). A confident "don't buy, cut it from stock" against stock
    that is not physically there stops a job, which is far worse than the
    over-buy it would have prevented. So the bias is: recommend, show the
    evidence, let a human say yes. Feedback on those yes/no calls is what
    eventually earns this the right to act on its own.
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from app.services import sku_geometry

logger = logging.getLogger(__name__)

# Preferred maximum drop per donor stick. Joey's rule of thumb: keep waste
# under a foot. Exceeding it is allowed but must be flagged, because clearing a
# job can be worth more than the steel (the shafts get cut with 3-4' of drop
# precisely because the lead time was worse than the waste).
DEFAULT_WASTE_TOLERANCE_INCHES = 12

# Kerf — material actually lost to the blade on each cut.
DEFAULT_KERF_INCHES = 0.125
KERF_BY_KIND = {
    "panel": 0.125,
    "shaft": 0.125,
}

# Fit tolerance — how far under nominal a finished piece may run and still be
# a good section. Per Joey (2026-07-20): blade thickness does not affect the
# size of a typical sectional door section; normal variance on a panel is an
# eighth to a quarter inch.
#
# This is what makes 2 x 16'2" come out of a 32'4" stick. Nominal is 388" from
# 388", so the 1/8" kerf has to come from somewhere — it comes out of the
# tolerance, leaving two sections each a sixteenth under. Without modelling
# this the solver reports a yield of ONE per stick and the buy list roughly
# doubles for every nested panel.
#
# 0.25 is the top of the range Joey quoted. Dropping it to 0.125 is the
# conservative setting: it still absorbs a single kerf but leaves no margin.
FIT_TOLERANCE_BY_KIND = {
    "panel": 0.25,
    "shaft": 0.0,      # not stated for shafts — assume none until told otherwise
}
DEFAULT_FIT_TOLERANCE_INCHES = 0.0


@dataclass
class CutPlan:
    """One donor stick and what comes off it."""

    donor_sku: str
    donor_length_inches: int
    pieces: List[int] = field(default_factory=list)   # piece lengths, inches
    waste_inches: float = 0.0

    @property
    def within_tolerance(self) -> bool:
        return self.waste_inches <= DEFAULT_WASTE_TOLERANCE_INCHES


@dataclass
class CutRecommendation:
    """A proposal to satisfy one short item by cutting a longer one."""

    target_sku: str
    target_length_inches: int
    qty_needed: float
    donor_sku: str
    donor_length_inches: int
    donor_on_hand: float
    donor_sticks_used: int
    pieces_yielded: int
    total_waste_inches: float
    within_tolerance: bool
    plans: List[CutPlan]
    jobs: List[str]
    unit_cost_avoided: float
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["plans"] = [
            {
                "donor_sku": p.donor_sku,
                "donor_length": sku_geometry.format_inches(p.donor_length_inches),
                "pieces": [sku_geometry.format_inches(x) for x in p.pieces],
                "waste": sku_geometry.format_inches(round(p.waste_inches)),
            }
            for p in self.plans
        ]
        d["target_length"] = sku_geometry.format_inches(self.target_length_inches)
        d["donor_length"] = sku_geometry.format_inches(self.donor_length_inches)
        d["total_waste"] = sku_geometry.format_inches(round(self.total_waste_inches))
        return d


def pack_pieces(
    donor_length: int,
    piece_length: int,
    qty_needed: int,
    donor_sticks_available: int,
    kerf: float = DEFAULT_KERF_INCHES,
    fit_tolerance: float = DEFAULT_FIT_TOLERANCE_INCHES,
) -> List[CutPlan]:
    """First-fit-decreasing pack of identical pieces into donor sticks.

    ``fit_tolerance`` is how far under nominal a finished piece may run and
    still be usable, which is what lets the blade kerf be absorbed instead of
    costing a whole piece. See FIT_TOLERANCE_BY_KIND.

    Uniform piece length keeps this exact: pieces-per-stick is a closed form,
    no search needed. Mixed-length nesting across different target SKUs in one
    family is a later refinement — it only pays off once feedback shows the
    single-target case is trusted.
    """
    if donor_length <= 0 or piece_length <= 0 or qty_needed <= 0:
        return []

    # Minimum acceptable finished length for one piece.
    effective_piece = piece_length - fit_tolerance
    if effective_piece > donor_length:
        return []

    # n pieces need (n-1) kerfs: the last cut frees the offcut, not a piece.
    per_stick = 1
    while True:
        nxt = per_stick + 1
        if nxt * effective_piece + (nxt - 1) * kerf <= donor_length:
            per_stick = nxt
        else:
            break

    plans: List[CutPlan] = []
    remaining = qty_needed
    sticks_used = 0
    while remaining > 0 and sticks_used < donor_sticks_available:
        take = min(per_stick, remaining)
        # Waste is measured against NOMINAL piece length, not the tolerance-
        # reduced one, so the drop reported is the real offcut a human will see
        # on the floor. Clamped at zero: when the tolerance absorbs the kerf
        # the arithmetic can go a fraction negative, which is not a negative
        # offcut, it is a piece finishing a sixteenth under nominal.
        consumed = take * piece_length + max(0, take - 1) * kerf
        plans.append(
            CutPlan(
                donor_sku="",  # filled by caller
                donor_length_inches=donor_length,
                pieces=[piece_length] * take,
                waste_inches=round(max(0.0, donor_length - consumed), 3),
            )
        )
        remaining -= take
        sticks_used += 1

    return plans


class CuttingStockService:
    """Finds cut-from-stock opportunities across a demand-engine result."""

    def analyze(
        self,
        rows: List[dict],
        waste_tolerance_inches: int = DEFAULT_WASTE_TOLERANCE_INCHES,
    ) -> List[CutRecommendation]:
        """Scan demand rows for shortfalls satisfiable by cutting surplus stock.

        ``rows`` must be the FULL row set including met items (``include_met=True``)
        — a row with net_need <= 0 is exactly the surplus that can donate, so
        filtering shortfalls first would hide every donor.
        """
        by_family: Dict[str, List[dict]] = {}
        geo_cache: Dict[str, sku_geometry.SkuGeometry] = {}

        for r in rows:
            sku = r.get("item_no") or ""
            geo = sku_geometry.parse(sku)
            if geo is None:
                continue
            geo_cache[sku] = geo
            by_family.setdefault(geo.family, []).append(r)

        recommendations: List[CutRecommendation] = []

        for family, members in by_family.items():
            shorts = [r for r in members if (r.get("net_need") or 0) > 0]
            if not shorts:
                continue

            # Donor pool: anything in the family physically on hand. Uses raw
            # on_hand rather than surplus-after-demand, because the engine's
            # demand figure is per-SKU and does not yet know that this stock is
            # about to be re-purposed. Committed quantity is netted below.
            donors = [r for r in members if (r.get("on_hand") or 0) > 0]
            if not donors:
                continue

            # Most-needed shortfalls first.
            shorts.sort(key=lambda r: r.get("net_need") or 0, reverse=True)
            donor_by_sku = {r["item_no"]: r for r in donors}

            # Track donor stock consumed within this pass so two shortfalls
            # cannot both claim the same stick.
            claimed: Dict[str, float] = {}

            for short in shorts:
                t_sku = short["item_no"]
                t_geo = geo_cache[t_sku]
                qty_needed = int(round(short.get("net_need") or 0))
                if qty_needed <= 0:
                    continue

                # Score every eligible donor and take the thriftiest, rather
                # than the first that fits. Sorting donors longest-first and
                # taking the first match maximises waste: it would cut a 15'6"
                # shaft down to a 9'6" (6' of drop) while an 10'6" sat on the
                # rack. Waste per piece is the metric that matters.
                while qty_needed > 0:
                    best = None
                    for donor in donors:
                        d_sku = donor["item_no"]
                        if d_sku == t_sku:
                            continue
                        d_geo = geo_cache[d_sku]

                        allowed, _why = sku_geometry.can_cut_from(d_sku, t_sku)
                        if not allowed:
                            continue

                        # Stock free after this donor's own committed demand
                        # and anything already claimed earlier in this pass.
                        own_demand = max(0.0, donor.get("demand") or 0)
                        free = (donor.get("on_hand") or 0) - own_demand - claimed.get(d_sku, 0.0)
                        available = int(free)
                        if available <= 0:
                            continue

                        cand = pack_pieces(
                            donor_length=d_geo.length_inches,
                            piece_length=t_geo.length_inches,
                            qty_needed=qty_needed,
                            donor_sticks_available=available,
                            kerf=KERF_BY_KIND.get(d_geo.kind, DEFAULT_KERF_INCHES),
                            fit_tolerance=FIT_TOLERANCE_BY_KIND.get(
                                d_geo.kind, DEFAULT_FIT_TOLERANCE_INCHES
                            ),
                        )
                        if not cand:
                            continue

                        yielded = sum(len(p.pieces) for p in cand)
                        waste = sum(p.waste_inches for p in cand)
                        # Waste per usable piece, so a stick that nests four
                        # pieces beats one that nests a single piece even if
                        # its absolute drop is larger.
                        score = waste / max(1, yielded)
                        if best is None or score < best[0]:
                            best = (score, d_sku, d_geo, cand, yielded, waste)

                    if best is None:
                        break

                    _score, d_sku, d_geo, plans, yielded, _waste = best
                    for p in plans:
                        p.donor_sku = d_sku

                    yielded = sum(len(p.pieces) for p in plans)
                    total_waste = sum(p.waste_inches for p in plans)
                    worst = max(p.waste_inches for p in plans)

                    claimed[d_sku] = claimed.get(d_sku, 0.0) + len(plans)

                    note = ""
                    if worst > waste_tolerance_inches:
                        note = (
                            f"drop of {sku_geometry.format_inches(round(worst))} per stick "
                            f"exceeds the {sku_geometry.format_inches(waste_tolerance_inches)} "
                            f"target — worth it only if it clears the job"
                        )

                    recommendations.append(
                        CutRecommendation(
                            target_sku=t_sku,
                            target_length_inches=t_geo.length_inches,
                            qty_needed=qty_needed,
                            donor_sku=d_sku,
                            donor_length_inches=d_geo.length_inches,
                            donor_on_hand=donor_by_sku[d_sku].get("on_hand") or 0,
                            donor_sticks_used=len(plans),
                            pieces_yielded=yielded,
                            total_waste_inches=round(total_waste, 2),
                            within_tolerance=worst <= waste_tolerance_inches,
                            plans=plans,
                            jobs=short.get("jobs") or [],
                            unit_cost_avoided=round(
                                min(yielded, qty_needed) * (short.get("unit_cost") or 0), 2
                            ),
                            note=note,
                        )
                    )

                    qty_needed -= yielded
                    if qty_needed <= 0:
                        break

        recommendations.sort(key=lambda r: r.unit_cost_avoided, reverse=True)
        return recommendations

    def summarize(self, recs: List[CutRecommendation]) -> dict:
        """Headline numbers for the digest / workbook."""
        return {
            "opportunity_count": len(recs),
            "items_covered": len({r.target_sku for r in recs}),
            "estimated_cost_avoided": round(sum(r.unit_cost_avoided for r in recs), 2),
            "within_tolerance": sum(1 for r in recs if r.within_tolerance),
            "over_tolerance": sum(1 for r in recs if not r.within_tolerance),
            "total_waste_inches": round(sum(r.total_waste_inches for r in recs), 1),
        }


cutting_stock_service = CuttingStockService()
