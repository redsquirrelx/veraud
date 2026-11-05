"""Composition root. The only new-code module wiring concrete adapters to ports."""
from dataclasses import dataclass
from shoplab.application.get_quote import GetQuote
from shoplab.application.list_products import ListProducts
from shoplab.application.quote_order import QuoteOrder
from shoplab.infrastructure.memory_catalog import MemoryProductCatalog
from shoplab.infrastructure.memory_promotions import MemoryPromotionCatalog
from shoplab.infrastructure.memory_quotes import MemoryQuoteRecorder
from shoplab.infrastructure.quote_ids import UuidQuoteIds
from shoplab.infrastructure.shipping_rates import TableShippingRates


@dataclass(frozen=True)
class ShopServices:
    list_products: ListProducts
    quote_order: QuoteOrder
    get_quote: GetQuote


def build_services() -> ShopServices:
    products = MemoryProductCatalog()
    quotes = MemoryQuoteRecorder()
    return ShopServices(
        list_products=ListProducts(products),
        quote_order=QuoteOrder(products, MemoryPromotionCatalog(),
                               TableShippingRates(), quotes, UuidQuoteIds()),
        get_quote=GetQuote(quotes),
    )
