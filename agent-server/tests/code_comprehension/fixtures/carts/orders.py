"""Minimal order submission and a runnable demonstration."""

from decimal import Decimal

from cart import Cart, preview_total
from pricing import PriceLine, calculate_total


def submit_order(cart: Cart, available_stock: dict[str, int], customer_code: str):
    if not customer_code.strip():
        return False
    if not cart.lines:
        return None
    if cart.status != "draft":
        return None
    if any(available_stock.get(line.sku, 0) < line.quantity for line in cart.lines):
        return False

    for line in cart.lines:
        available_stock[line.sku] -= line.quantity
    cart.status = "submitted"
    cart.revision += 1
    return f"ORD-{customer_code.upper()}-{cart.revision:04d}"


def main() -> None:
    lines = [
        PriceLine("BOOK", Decimal("25.00"), 2),
        PriceLine("PEN", Decimal("5.00"), 1),
    ]
    print("Precio sin cupón:", calculate_total(lines))

    cart = Cart(lines=lines, coupon="WELCOME")
    print("Vista previa 1:", preview_total(cart))
    print("Vista previa 2:", preview_total(cart))
    print("Cupón tras previsualizar:", cart.coupon)
    print("Revisión tras previsualizar:", cart.revision)

    stock = {"BOOK": 5, "PEN": 5}
    print("Pedido válido:", submit_order(cart, stock, "client7"))
    print("Pedido repetido:", submit_order(cart, stock, "client7"))
    print("Cliente vacío:", submit_order(Cart(lines=lines), stock, ""))
    print("Stock insuficiente:", submit_order(Cart(lines=lines), {}, "client7"))


if __name__ == "__main__":
    main()
