"""Small record operations shared by investigator evaluation steps."""


def retain_previous[T](current: list[T], previous: list[T], *, identity: str = "id") -> list[T]:
    """Keep current records first, then prior records not replaced by their identity.

    Duplicates within either input remain visible to domain validation; this is
    accumulation across iterations, not deduplication or evidence acceptance.
    """
    replaced = {getattr(record, identity) for record in current}
    return [*current, *(record for record in previous if getattr(record, identity) not in replaced)]
