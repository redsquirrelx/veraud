"""Legacy preview endpoint used by marketing support tooling."""
from shoplab.infrastructure.memory_promotions import MemoryPromotionCatalog


def preview_discount(code: str, subtotal_cents: int) -> int:
    promotion = MemoryPromotionCatalog().find(code)
    if promotion is None:
        return 0
    return promotion.discount_for(subtotal_cents)
