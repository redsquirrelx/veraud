def invoice_value(entries):
    result = 0
    for entry in entries:
        result += entry["amount"]
    return round(result, 2)
