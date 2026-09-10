"""Log prefixer so strategy output is distinguishable in a shared process."""

import logging
from typing import Any, MutableMapping, Tuple


class PrefixLogger(logging.LoggerAdapter):
    def __init__(self, logger: logging.Logger, tag: str):
        super().__init__(logger, {"tag": tag})
        self.tag = tag

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> Tuple[str, MutableMapping[str, Any]]:
        return f"[{self.tag}] {msg}", kwargs
