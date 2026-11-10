"""Replaceable catalog adapter. In-memory data is intentionally nonpersistent."""
from shoplab.domain.catalog import Product

_DEFAULT_PRODUCTS = (
    Product("BOOK", "Hardcover notebook", 1500, 450),
    Product("PEN", "Fine-tip pen", 250, 15),
    Product("BAG", "Canvas bag", 3500, 900),
    Product("ARCHIVE", "Discontinued archive folder", 600, 120, active=False),
)


class MemoryProductCatalog:
    def __init__(self, products: tuple[Product, ...] = _DEFAULT_PRODUCTS) -> None:
        self._products = {p.sku: p for p in products}

    def get(self, sku: str) -> Product | None:
        return self._products.get(sku)

    def list_active(self) -> tuple[Product, ...]:
        return tuple(sorted((p for p in self._products.values() if p.active),
                            key=lambda p: p.sku))
