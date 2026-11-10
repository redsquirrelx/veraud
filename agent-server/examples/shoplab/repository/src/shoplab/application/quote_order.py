"""Quote a checkout without depending on storage, HTTP, or console adapters."""
from dataclasses import dataclass
from shoplab.application.contracts import (
    ProductCatalog, PromotionCatalog, ShippingRateProvider, QuoteRecorder,
    QuoteIdFactory, StoredQuote,
)
from shoplab.domain.shipping import Parcel, DeliveryZone


class QuoteError(ValueError):
    """Invalid quote input or unavailable product."""


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    sku: str
    quantity: int
    zone: DeliveryZone
    promotion_code: str | None = None


@dataclass(frozen=True, slots=True)
class QuoteResult:
    quote_id: str
    sku: str
    quantity: int
    subtotal_cents: int
    discount_cents: int
    delivery_cents: int
    total_cents: int


class QuoteOrder:
    def __init__(self, products: ProductCatalog, promotions: PromotionCatalog,
                 rates: ShippingRateProvider, recorder: QuoteRecorder,
                 ids: QuoteIdFactory) -> None:
        self._products = products
        self._promotions = promotions
        self._rates = rates
        self._recorder = recorder
        self._ids = ids

    def execute(self, request: QuoteRequest) -> QuoteResult:
        if request.quantity <= 0 or request.quantity > 100:
            raise QuoteError("quantity must be between 1 and 100")
        product = self._products.get(request.sku)
        if product is None or not product.active:
            raise QuoteError("product not found or inactive")
        subtotal = product.subtotal(request.quantity)
        discount = 0
        if request.promotion_code:
            promotion = self._promotions.find(request.promotion_code.upper())
            if promotion is None:
                raise QuoteError("unknown promotion")
            discount = promotion.discount_for(subtotal)
        try:
            parcel = Parcel(product.weight_grams * request.quantity, request.zone)
        except ValueError as error:
            raise QuoteError(str(error)) from error
        delivery = self._rates.price_cents(parcel)
        if delivery < 0:
            raise RuntimeError("shipping adapter returned negative charge")
        total = subtotal - discount + delivery
        quote_id = self._ids.new_id()
        result = QuoteResult(quote_id, product.sku, request.quantity, subtotal,
                             discount, delivery, total)
        self._recorder.save(StoredQuote(quote_id, product.sku, request.quantity, total))
        return result
