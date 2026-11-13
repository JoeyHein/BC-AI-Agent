"""Decimal helpers for the freight estimator.

Money and billed weight round half up to the cent and the hundredth of a
pound. Binary floats are not used for the charge arithmetic.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def pounds(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def as_number(value: Decimal):
    """JSON number. Already quantized, so the cent is the value the UI shows."""
    return float(value)
