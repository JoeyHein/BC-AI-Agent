"""Verify the volume curve excludes ALUM and applies correctly to the rest."""
from app.services.escalating_margin_service import get_profile_by_key


def main():
    profile = get_profile_by_key("GNB_MANITOBA")

    # Synthetic quote: 3 commercial doors at $5k each (base 30% GM list) +
    # 2 aluminum panels at $2k each. Total $19k mixed.
    lines = {
        "L1": {"price": 5000, "qty": 3, "posting_group": "COMM"},
        "L2": {"price": 2000, "qty": 2, "posting_group": "ALUM"},
        "L3": {"price": 1500, "qty": 1, "posting_group": "RESI"},
    }

    curve_lines, excluded = profile.split_lines(lines)
    curve_total = profile.curve_subtotal(lines)
    print(f"Lines on curve     : {list(curve_lines.keys())}")
    print(f"Lines excluded     : {list(excluded.keys())}")
    print(f"Curve subtotal     : ${curve_total:,.2f}")
    print(f"Excluded subtotal  : ${sum(lp['price']*lp['qty'] for lp in excluded.values()):,.2f}")

    calc = profile.calculate(curve_total)
    print(f"\nVolume curve at curve subtotal:")
    print(f"  target GM%       : {calc['target_gm']}")
    print(f"  multiplier       : {calc['multiplier']}")
    print(f"  discount         : {calc['discount_pct']}%")

    print("\nFinal per-line pricing:")
    for line_id, lp in lines.items():
        if line_id in curve_lines:
            new = round(lp["price"] * calc["multiplier"], 2)
            print(f"  {line_id} ({lp['posting_group']:5}) qty={lp['qty']}: "
                  f"${lp['price']} -> ${new} (curve applied)")
        else:
            print(f"  {line_id} ({lp['posting_group']:5}) qty={lp['qty']}: "
                  f"${lp['price']} (unchanged — aluminum)")


if __name__ == "__main__":
    main()
