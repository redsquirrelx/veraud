"""One audit-wide token ledger, reserved per provider attempt rather than per agent."""

from threading import RLock


class SharedTokenBudget:
    """Thread-safe scopes share a cap; parent scopes include all descendant usage.

    Unreported, failed and cancelled attempts retain their conservative estimate.
    Known usage replaces the estimate, freeing unused capacity for other agents.
    """

    def __init__(self, limit: int, *, parent: "SharedTokenBudget | None" = None):
        if limit < 1:
            raise ValueError("Token budget must be positive.")
        self.limit = limit
        self.parent = parent
        self.root = parent.root if parent is not None else self
        self._lock = parent._lock if parent is not None else RLock()
        self.used = 0
        self.estimated = 0

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.limit - self.root.used)

    def fork(self) -> "SharedTokenBudget":
        return SharedTokenBudget(self.limit, parent=self)

    def _adjust(self, tokens: int, estimated: int) -> None:
        scope = self
        while scope is not None:
            scope.used += tokens
            scope.estimated += estimated
            scope = scope.parent

    def reserve(self, tokens: int) -> "TokenReservation | None":
        if tokens < 1:
            raise ValueError("Token reservation must be positive.")
        with self._lock:
            if tokens > self.remaining:
                return None
            self._adjust(tokens, tokens)
            return TokenReservation(self, tokens)


class TokenReservation:
    def __init__(self, scope: SharedTokenBudget, tokens: int):
        self.scope, self.tokens = scope, tokens
        self._settled = False

    def settle(self, actual: int) -> None:
        if actual < 0:
            raise ValueError("Token usage cannot be negative.")
        with self.scope._lock:
            if self._settled:
                raise ValueError("Reservation already settled.")
            self.scope._adjust(actual - self.tokens, -self.tokens)
            self._settled = True
