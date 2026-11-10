"""Shipping value objects and deterministic parcel calculations."""
from dataclasses import dataclass
from enum import Enum


class DeliveryZone(str, Enum):
    LOCAL = "local"
    NATIONAL = "national"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class Parcel:
    weight_grams: int
    zone: DeliveryZone

    def __post_init__(self) -> None:
        if self.weight_grams <= 0 or self.weight_grams > 50_000:
            raise ValueError("parcel weight must be in 1..50000 grams")

    @property
    def billable_kilograms(self) -> int:
        return (self.weight_grams + 999) // 1000
