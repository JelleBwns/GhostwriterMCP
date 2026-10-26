import json
import logging
from datetime import datetime, timezone


class JsonLog(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


def configure_logging(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger("gw_reporting")
    if not target.handlers:
        target.addHandler(logging.StreamHandler())
    for handler in target.handlers:
        handler.setFormatter(JsonLog())
    target.setLevel(logging.INFO)
