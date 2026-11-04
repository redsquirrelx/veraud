STOCK: dict[str, int] = {"BOOK": 10, "PEN": 20}


def read(sku: str) -> int:
    return STOCK.get(sku, 0)


def decrement(sku: str, count: int) -> bool:
    available = read(sku)
    if count <= 0 or available < count:
        return False
    STOCK[sku] = available - count
    return True
