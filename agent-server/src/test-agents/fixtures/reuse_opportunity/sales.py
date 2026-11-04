def order_cost(items):
    amounts = [item["amount"] for item in items]
    return round(sum(amounts), 2)
