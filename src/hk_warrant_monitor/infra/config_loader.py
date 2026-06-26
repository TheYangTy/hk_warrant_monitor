from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv_file(PROJECT_ROOT / ".env")
    settings_path = Path(path) if path else PROJECT_ROOT / "config" / "settings.toml"
    with settings_path.open("rb") as f:
        settings = tomllib.load(f)

    futu = settings.setdefault("futu", {})
    futu["host"] = os.getenv(futu.get("host_env", "FUTU_HOST"), futu.get("default_host", "127.0.0.1"))
    futu["port"] = int(os.getenv(futu.get("port_env", "FUTU_PORT"), futu.get("default_port", 11111)))

    feishu = settings.setdefault("feishu", {})
    feishu["webhook_url"] = os.getenv(feishu.get("webhook_url_env", "FEISHU_WEBHOOK_URL"), "")
    feishu["secret"] = os.getenv(feishu.get("secret_env", "FEISHU_SECRET"), "")

    ai = settings.setdefault("ai", {})
    ai["enabled"] = _env_bool(
        ai.get("enabled_env", "AI_ENABLED"),
        bool(ai.get("default_enabled", False)),
    )
    ai["provider"] = os.getenv(ai.get("provider_env", "AI_PROVIDER"), ai.get("default_provider", "deepseek"))
    ai["api_key"] = os.getenv(ai.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    ai["model"] = os.getenv(ai.get("model_env", "AI_MODEL"), ai.get("default_model", "deepseek-v4-flash"))
    ai["daily_limit"] = int(os.getenv(ai.get("daily_limit_env", "AI_DAILY_LIMIT"), ai.get("default_daily_limit", 50)))
    ai["cooldown_minutes"] = int(
        os.getenv(ai.get("cooldown_minutes_env", "AI_COOLDOWN_MINUTES"), ai.get("default_cooldown_minutes", 15))
    )
    ai["min_confidence"] = int(
        os.getenv(ai.get("min_confidence_env", "AI_MIN_CONFIDENCE"), ai.get("default_min_confidence", 72))
    )
    ai["style"] = os.getenv(ai.get("style_env", "AI_STYLE"), ai.get("default_style", "TRADER_BRIEF"))
    return settings


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def project_path(relative: str) -> Path:
    return PROJECT_ROOT / relative
