# API-001 — Developer Interface Contract

## Status and scope

This file specifies the working local CLI and development-only WSGI API. It is not a versioned internet-facing service contract. New workflow monetary amounts are integer cents; the legacy demo uses its historical integer amounts.

## CLI

```bash
python -m shoplab.presentation.cli catalog
python -m shoplab.presentation.cli quote --sku BOOK --quantity 2 --zone national --promotion WELCOME10
```

`catalog` outputs a JSON list of `{sku, title, unit_price_cents}`; inactive items are omitted. `quote` outputs:

```json
{
  "quote_id": "Q-EXAMPLEONLY",
  "sku": "BOOK",
  "quantity": 2,
  "subtotal_cents": 3000,
  "discount_cents": 300,
  "delivery_cents": 1000,
  "total_cents": 3700
}
```

The ID shown is illustrative. Invalid input yields JSON `error` and exit code 2.

## WSGI HTTP API

`GET /health` -> `200` with `{"status":"ok","persistence":"memory"}`.

`GET /catalog` -> `200` with the active product list.

`POST /quotes` -> `201` with a `QuoteResult`. Example request:

```json
{"sku":"BOOK","quantity":2,"zone":"national","promotion_code":"WELCOME10"}
```

Required: `sku` (string), `quantity` (integer). Optional: `zone` (`local`, `national`, `remote`; defaults to `local`), `promotion_code` (string or omitted). Invalid payloads return `400` with an `error` string. Unknown routes return `404`.

## Validation boundaries

Quantity: 1 through 100. Parcel weight: 1 through 50,000 grams. Maximum accepted HTTP request body: 8192 bytes. Catalog contains active and inactive products; inactive products cannot be quoted. A quote does not reserve stock or create a paid order.

## Example tariffs

The local carrier adapter charges base plus 100 cents per rounded-up kilogram: local base 400; national 900; remote 1800. These represent development fixtures, not a business SLA.
