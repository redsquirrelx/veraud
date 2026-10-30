"""Counterexample: multiple collaborators, one explicit orchestration purpose."""


def place_order(items, repository, notifier):
    total = sum(item["price"] for item in items)
    order = repository.save({"items": items, "total": total})
    notifier.send_confirmation(order)
    return order
