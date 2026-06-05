"""
Reverse-engineer the GNB Manitoba pricing grid into pure multipliers.

The current GNB pricing engine (escalating_margin_service.py) is a volume
discount curve:
  - Every line is priced at base GM 30% (cost × 1.4286)
  - At quote-total breakpoints, target GM drops along a piecewise-linear curve
  - A volume_multiplier is applied to every line in the quote

This script inverts that into the multiplier grid the user wants — a
table where, for any quote-total volume, you can read off:
  - effective GM%
  - cost-to-price multiplier (cost × m = price)
  - volume discount % from the base 30%-GM list
"""
from app.services.escalating_margin_service import get_profile_by_key


def main():
    profile = get_profile_by_key("GNB_MANITOBA")
    base_gm = profile.base_gm_pct
    base_multiplier = 1 / (1 - base_gm / 100)

    print(f"GNB Manitoba pricing — reverse-engineered from {profile.name}\n")
    print(f"Base GM (list price level)             : {base_gm:.1f}%")
    print(f"Base cost-to-price multiplier          : {base_multiplier:.4f}  "
          f"(price = cost × {base_multiplier:.4f})")
    print(f"Profile breakpoints (GM falls as quote total grows):")
    for bp in profile.breakpoints:
        print(f"  ${bp.value_threshold:>10,.0f}  ->  {bp.target_gm_pct:.1f}% GM")
    print()

    # Build a dense lookup grid. The discontinuities are at the breakpoints,
    # but we sample more densely so the user can see the curve clearly.
    sample_volumes = [
        0, 5_000, 10_000, 13_000, 16_000, 20_000, 25_000, 30_000, 38_000,
        50_000, 75_000, 100_000, 130_000, 160_000, 180_000, 220_000, 300_000,
    ]

    print("=" * 88)
    print(f"{'Quote total':>14} | {'Target GM%':>10} | {'Cost mult':>10} | "
          f"{'Volume discount':>15} | {'Margin $/unit':>14}")
    print(f"{'(at base 30%)':>14} | {'(applied)':>10} | {'(cost→price)':>10} | "
          f"{'(off list)':>15} | {'on $100 cost':>14}")
    print("=" * 88)
    for vol in sample_volumes:
        result = profile.calculate(vol)
        target_gm = result["target_gm"]
        volume_mult = result["multiplier"]            # off the base 30% list
        cost_mult = base_multiplier * volume_mult     # cost → final price
        discount = result["discount_pct"]
        # On a $100 cost item, margin in dollars at the final price
        price_at_100 = 100 * cost_mult
        margin_dollars = price_at_100 - 100
        print(f"${vol:>13,.0f} | {target_gm:>9.2f}% | {cost_mult:>10.4f} | "
              f"{discount:>14.2f}% | ${margin_dollars:>13.2f}")
    print("=" * 88)
    print()
    print("How to read this:")
    print(f"  • A GNB quote with $25,000 in line items priced at the base 30%-GM list")
    print(f"    settles at ~{profile.calculate(25_000)['target_gm']:.1f}% effective GM,")
    print(f"    so every line gets multiplied by {profile.calculate(25_000)['multiplier']:.4f}")
    print(f"    (a {profile.calculate(25_000)['discount_pct']:.1f}% discount).")
    print(f"  • For BC SalesPriceLists: bake the BASE list at cost × {base_multiplier:.4f}")
    print(f"    into a 'GNB' Customer Price Group, then keep the volume escalation")
    print(f"    as a quote-time line discount (BC can't natively express the curve).")
    print(f"  • If a static grid is preferred, pick the GM% that matches your")
    print(f"    typical GNB quote size and bake one flat multiplier — but you'll")
    print(f"    overcharge small quotes and undercharge big ones vs. today.")


if __name__ == "__main__":
    main()
