from shoplab.domain.models import Order
from shoplab.inventory import allocator


def can_fulfill(sku: str) -> bool:
    return sku != "BLOCKED"


def create_order(order: Order) -> bool:
    return allocator.allocate(order.sku, order.quantity)
