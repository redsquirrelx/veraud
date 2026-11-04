from shoplab.inventory.api import reserve_stock
from shoplab.orders import service as order_service


def allocate(sku: str, quantity: int) -> bool:
    if not order_service.can_fulfill(sku):
        return False
    return reserve_stock(sku, quantity)
