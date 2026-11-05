from shoplab.application.checkout import process_order
from shoplab.domain.models import Order


def main() -> None:
    ok, amount = process_order(Order("ORD-001", "BOOK", 2, 15))
    print(f"success={ok} amount={amount}")


if __name__ == "__main__":
    main()
