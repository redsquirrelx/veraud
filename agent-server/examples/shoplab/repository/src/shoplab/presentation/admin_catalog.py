"""Experimental internal support endpoint (not part of the public API)."""
from shoplab.infrastructure.memory_catalog import MemoryProductCatalog


def raw_catalog_snapshot(catalog: MemoryProductCatalog) -> dict[str, int]:
    return {sku: product.unit_price_cents for sku, product in catalog._products.items()}
