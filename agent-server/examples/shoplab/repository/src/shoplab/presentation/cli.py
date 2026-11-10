"""Command-line inbound adapter. All JSON values represent integer cents."""
import argparse
import json
from dataclasses import asdict
from shoplab.application.quote_order import QuoteRequest, QuoteError
from shoplab.bootstrap import build_services
from shoplab.domain.shipping import DeliveryZone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shoplab", description="ShopLab local demo")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="Show active products")
    quote = sub.add_parser("quote", help="Calculate and store a quote")
    quote.add_argument("--sku", required=True)
    quote.add_argument("--quantity", type=int, required=True)
    quote.add_argument("--zone", choices=[z.value for z in DeliveryZone],
                       default="local")
    quote.add_argument("--promotion")
    args = parser.parse_args(argv)
    services = build_services()
    try:
        if args.command == "catalog":
            result = [asdict(p) for p in services.list_products.execute()]
        else:
            result = asdict(services.quote_order.execute(QuoteRequest(
                args.sku, args.quantity, DeliveryZone(args.zone), args.promotion)))
    except (QuoteError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
