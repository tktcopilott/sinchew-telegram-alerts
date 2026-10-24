"""Configuration and credential validation at the application boundary."""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from .domain import ConfigurationError


@dataclass(frozen=True)
class Config:
    tag_id: int = 1495
    label: str = "Sin Chew · 诈骗"
    max_pages: int = 20
    baseline_pages: int = 2
    max_deliveries: int = 50
    heartbeat_hours: int = 24
    state_branch: str = "monitor-state"

    @classmethod
    def load(cls, path: Path):
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
            if set(value) - {"monitor"}:
                raise ValueError("unknown section")
            config = cls(**value.get("monitor", {}))
            for name, low, high in (("tag_id", 1, 10**9), ("max_pages", 2, 100),
                                    ("baseline_pages", 2, 100), ("max_deliveries", 1, 100),
                                    ("heartbeat_hours", 0, 168)):
                number = getattr(config, name)
                if type(number) is not int or not low <= number <= high:
                    raise ValueError("out-of-range setting")
            if config.baseline_pages > config.max_pages:
                raise ValueError("baseline exceeds page limit")
            if not isinstance(config.label, str) or not 1 <= len(config.label) <= 100:
                raise ValueError("invalid label")
            if not isinstance(config.state_branch, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config.state_branch):
                raise ValueError("invalid branch")
            return config
        except (OSError, ValueError, TypeError):
            raise ConfigurationError("Invalid monitor.toml. Check the documented fields and allowed ranges.") from None


def require_secret(environment, name: str) -> str:
    value = environment.get(name, "").strip()
    valid = bool(value)
    if name == "TELEGRAM_BOT_TOKEN":
        valid = bool(re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", value))
    elif name == "TELEGRAM_CHAT_ID":
        valid = bool(re.fullmatch(r"-?\d+", value))
    if not valid:
        raise ConfigurationError(f"Missing or invalid {name}. Set it as a GitHub Actions repository secret.")
    return value
