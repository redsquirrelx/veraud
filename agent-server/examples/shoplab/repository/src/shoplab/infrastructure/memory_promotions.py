"""Local promotion adapter for development and deterministic tests."""
from shoplab.domain.promotions import Promotion


class MemoryPromotionCatalog:
    def __init__(self, promotions: tuple[Promotion, ...] | None = None) -> None:
        if promotions is None:
            promotions = (
                Promotion("WELCOME10", 10),
                Promotion("SAVE20", 20, minimum_subtotal_cents=3000,
                          maximum_discount_cents=1000),
            )
        self._promotions = {p.code.upper(): p for p in promotions}

    def find(self, code: str) -> Promotion | None:
        return self._promotions.get(code.upper())
