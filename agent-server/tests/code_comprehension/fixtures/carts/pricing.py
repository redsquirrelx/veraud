"""Pure, explicitly defined invoice calculations."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


@dataclass(frozen=True)
class PriceLine:
    sku: str
    unit_price: Decimal
    quantity: int


def calculate_total(
    lines: list[PriceLine],
    *,
    discount_rate: Decimal = Decimal("0"),
    tax_rate: Decimal = Decimal("0.18"),
) -> Decimal:
    """Return the final amount after discount and tax, rounded to cents.

    The discount applies to the subtotal before tax. Neither ``lines`` nor
    their items are modified. Rates must be between zero and one, inclusive.
    """
    if not Decimal("0") <= discount_rate <= Decimal("1"):
        raise ValueError("discount_rate must be between 0 and 1")
    if not Decimal("0") <= tax_rate <= Decimal("1"):
        raise ValueError("tax_rate must be between 0 and 1")

    subtotal = Decimal("0")
    for line in lines:
        if line.quantity < 1 or line.unit_price < 0:
            raise ValueError("quantity must be positive and unit_price nonnegative")
        subtotal += line.unit_price * line.quantity

    discounted_subtotal = subtotal * (Decimal("1") - discount_rate)
    final_amount = discounted_subtotal * (Decimal("1") + tax_rate)
    return final_amount.quantize(CENT, rounding=ROUND_HALF_UP)
