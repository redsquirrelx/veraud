"""Text templates owned by the presentation channel."""


def render_receipt(order_id: str, total_cents: int) -> str:
    return f"Receipt for {order_id}: {total_cents} cents"
