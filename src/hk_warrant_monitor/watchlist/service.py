from __future__ import annotations

from hk_warrant_monitor.core.enums import Direction, RiskLevel
from hk_warrant_monitor.core.models import WatchItem
from hk_warrant_monitor.infra.database import Database


def normalize_hk_code(code: str) -> str:
    value = code.strip().upper()
    if value.startswith("HK."):
        return value
    if value.endswith(".HK"):
        return f"HK.{value[:-3]}"
    if value.isdigit():
        return f"HK.{value.zfill(5)}"
    return value


class WatchlistService:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        code: str,
        name: str,
        direction: Direction,
        risk_level: RiskLevel,
        allow_overnight: bool,
        enable: bool = True,
    ) -> WatchItem:
        item = WatchItem(
            code=normalize_hk_code(code),
            name=name,
            direction=direction,
            risk_level=risk_level,
            allow_overnight=allow_overnight,
            enable=enable,
        )
        self.db.execute(
            """
            INSERT INTO watchlist (code, name, direction, risk_level, allow_overnight, enable)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
              name=excluded.name,
              direction=excluded.direction,
              risk_level=excluded.risk_level,
              allow_overnight=excluded.allow_overnight,
              enable=excluded.enable,
              updated_at=CURRENT_TIMESTAMP
            """,
            (item.code, item.name, item.direction.value, item.risk_level.value, int(item.allow_overnight), int(item.enable)),
        )
        return item

    def remove(self, code: str) -> bool:
        normalized = normalize_hk_code(code)
        self.db.execute("DELETE FROM watchlist WHERE code = ?", (normalized,))
        return True

    def set_enabled(self, code: str, enable: bool) -> None:
        self.db.execute(
            "UPDATE watchlist SET enable = ?, updated_at = CURRENT_TIMESTAMP WHERE code = ?",
            (int(enable), normalize_hk_code(code)),
        )

    def list(self, enabled_only: bool = False) -> list[WatchItem]:
        sql = "SELECT * FROM watchlist"
        if enabled_only:
            sql += " WHERE enable = 1"
        sql += " ORDER BY code"
        return [self._row_to_item(row) for row in self.db.fetchall(sql)]

    def _row_to_item(self, row) -> WatchItem:
        return WatchItem(
            code=row["code"],
            name=row["name"],
            direction=Direction(row["direction"]),
            risk_level=RiskLevel(row["risk_level"]),
            allow_overnight=bool(row["allow_overnight"]),
            enable=bool(row["enable"]),
        )

