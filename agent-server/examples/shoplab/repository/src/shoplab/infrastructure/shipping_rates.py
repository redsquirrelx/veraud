"""Deterministic rate adapter representing an external carrier integration."""
from shoplab.domain.shipping import DeliveryZone, Parcel


class TableShippingRates:
    _BASE_CENTS = {DeliveryZone.LOCAL: 400,
                   DeliveryZone.NATIONAL: 900,
                   DeliveryZone.REMOTE: 1800}

    def price_cents(self, parcel: Parcel) -> int:
        return self._BASE_CENTS[parcel.zone] + parcel.billable_kilograms * 100
