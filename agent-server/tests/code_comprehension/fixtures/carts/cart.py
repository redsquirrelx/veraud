"""Shopping-cart state and total previews."""

from dataclasses import dataclass, field
from decimal import Decimal

from pricing import PriceLine, calculate_total


@dataclass
class Cart:
    lines: list[PriceLine] = field(default_factory=list)
    coupon: str | None = None
    revision: int = 0
    status: str = "draft"


def preview_total(cart: Cart) -> Decimal:
    """Show the current total before an order is submitted."""
    discount_rate = Decimal("0")
    if cart.coupon == "WELCOME":
        discount_rate = Decimal("0.10")
        cart.coupon = None
        cart.revision += 1
    return calculate_total(cart.lines, discount_rate=discount_rate)
