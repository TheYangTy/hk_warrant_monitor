from __future__ import annotations

from hk_warrant_monitor.core.models import Position
from hk_warrant_monitor.infra.database import Database
from hk_warrant_monitor.watchlist.service import normalize_hk_code


class PositionService:
    def __init__(self, db: Database):
        self.db = db

    def add(self, product_code: str, buy_price: float, quantity: int, buy_time: str) -> Position:
        code = normalize_hk_code(product_code)
        self.db.execute(
            "INSERT INTO position (product_code, buy_price, quantity, buy_time) VALUES (?, ?, ?, ?)",
            (code, buy_price, quantity, buy_time),
        )
        row = self.db.fetchone(
            "SELECT * FROM position WHERE product_code = ? ORDER BY id DESC LIMIT 1",
            (code,),
        )
        return self._row_to_position(row)

    def list(self, open_only: bool = True) -> list[Position]:
        sql = "SELECT * FROM position"
        if open_only:
            sql += " WHERE status = 'OPEN'"
        sql += " ORDER BY buy_time DESC, id DESC"
        return [self._row_to_position(row) for row in self.db.fetchall(sql)]

    def close(self, position_id: int) -> None:
        self.db.execute(
            "UPDATE position SET status = 'CLOSED', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (position_id,),
        )

    def delete(self, position_id: int) -> None:
        self.db.execute("DELETE FROM position WHERE id = ?", (position_id,))

    def _row_to_position(self, row) -> Position:
        return Position(
            id=int(row["id"]),
            product_code=row["product_code"],
            buy_price=float(row["buy_price"]),
            quantity=int(row["quantity"]),
            buy_time=row["buy_time"],
            status=row["status"],
        )
