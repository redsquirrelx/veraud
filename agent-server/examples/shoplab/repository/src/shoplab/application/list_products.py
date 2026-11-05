"""Query use case exposing product data without exposing repository internals."""
from dataclasses import dataclass
from shoplab.application.contracts import ProductCatalog


@dataclass(frozen=True, slots=True)
class ProductView:
    sku: str
    title: str
    unit_price_cents: int


class ListProducts:
    def __init__(self, products: ProductCatalog) -> None:
        self._products = products

    def execute(self) -> tuple[ProductView, ...]:
        return tuple(ProductView(p.sku, p.title, p.unit_price_cents)
                     for p in self._products.list_active())
