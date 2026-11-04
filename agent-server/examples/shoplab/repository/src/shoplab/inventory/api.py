from shoplab.inventory import _store


def available_stock(sku: str) -> int:
    return _store.read(sku)


def reserve_stock(sku: str, count: int) -> bool:
    return _store.decrement(sku, count)
