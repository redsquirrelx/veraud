"""Use-case owned abstractions. Concrete adapters must implement these ports."""
from typing import Protocol
from shoplab.domain.catalog import Product
from shoplab.domain.promotions import Promotion
from shoplab.domain.shipping import Parcel


class ProductCatalog(Protocol):
    def get(self, sku: str) -> Product | None: ...
    def list_active(self) -> tuple[Product, ...]: ...


class PromotionCatalog(Protocol):
    def find(self, code: str) -> Promotion | None: ...


class ShippingRateProvider(Protocol):
    def price_cents(self, parcel: Parcel) -> int: ...


class QuoteRecorder(Protocol):
    def save(self, quote: "StoredQuote") -> None: ...
    def get(self, quote_id: str) -> "StoredQuote | None": ...


class QuoteIdFactory(Protocol):
    def new_id(self) -> str: ...


from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class StoredQuote:
    quote_id: str
    sku: str
    quantity: int
    total_cents: int
