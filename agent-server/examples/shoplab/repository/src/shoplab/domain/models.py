from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    order_id: str
    sku: str
    quantity: int
    unit_price: int

    @property
    def total(self) -> int:
        return self.quantity * self.unit_price
