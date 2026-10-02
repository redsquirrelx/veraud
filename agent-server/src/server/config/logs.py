import logging
import os

_configured = False


def setup_logging(level: int | None = None) -> None:
    """Configure the root handler once. Safe to call multiple times."""
    global _configured
    if _configured:
        return
    resolved = level or getattr(
        logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )
    _configured = True


def get_logger(tag: str) -> logging.Logger:
    """Return a tagged logger, e.g. get_logger("dummy-agent")."""
    setup_logging()
    return logging.getLogger(f"server.{tag}")
