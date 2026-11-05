"""Catalog concepts. This module contains no adapter or transport knowledge."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Product:
    sku: str
    title: str
    unit_price_cents: int
    weight_grams: int
    active: bool = True

    def __post_init__(self) -> None:
        if not self.sku.strip() or not self.title.strip():
            raise ValueError("sku and title are required")
        if self.unit_price_cents < 0 or self.weight_grams <= 0:
            raise ValueError("price must be non-negative; weight must be positive")

    def subtotal(self, quantity: int) -> int:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        return self.unit_price_cents * quantity
