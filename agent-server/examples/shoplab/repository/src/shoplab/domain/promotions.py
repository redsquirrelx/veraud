"""Pure discount calculations with integer-cent arithmetic."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Promotion:
    code: str
    percent_off: int
    minimum_subtotal_cents: int = 0
    maximum_discount_cents: int | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or not 0 <= self.percent_off <= 100:
            raise ValueError("invalid promotion")
        if self.minimum_subtotal_cents < 0:
            raise ValueError("negative minimum")
        if self.maximum_discount_cents is not None and self.maximum_discount_cents < 0:
            raise ValueError("negative discount cap")

    def discount_for(self, subtotal_cents: int) -> int:
        if subtotal_cents < 0:
            raise ValueError("negative subtotal")
        if subtotal_cents < self.minimum_subtotal_cents:
            return 0
        discount = subtotal_cents * self.percent_off // 100
        if self.maximum_discount_cents is not None:
            discount = min(discount, self.maximum_discount_cents)
        return discount
