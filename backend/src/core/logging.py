import logging


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging; `level` is a name like "INFO" or "DEBUG"."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
