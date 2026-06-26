from __future__ import annotations

import hashlib
import logging

from hk_warrant_monitor.core.enums import PushLevel
from hk_warrant_monitor.infra.database import Database
from hk_warrant_monitor.notifications.feishu_client import FeishuClient


class PushService:
    def __init__(self, db: Database, feishu: FeishuClient, logger: logging.Logger):
        self.db = db
        self.feishu = feishu
        self.logger = logger

    def push(self, level: PushLevel, scene: str, target_code: str, title: str, markdown: str) -> bool:
        dedupe_key = self._dedupe_key(scene, target_code, markdown)
        if self.db.fetchone("SELECT 1 FROM push_record WHERE dedupe_key = ?", (dedupe_key,)):
            self.logger.info("Skip duplicate push: %s %s", scene, target_code)
            return False

        sent = False
        if self.feishu.enabled():
            sent = self.feishu.send_markdown(title, markdown)
        else:
            self.logger.info("Feishu disabled. Message preview:\n%s", markdown)

        self.db.execute(
            "INSERT OR IGNORE INTO push_record (dedupe_key, level, scene, target_code, content) VALUES (?, ?, ?, ?, ?)",
            (dedupe_key, level.value, scene, target_code, markdown),
        )
        return sent

    def _dedupe_key(self, scene: str, target_code: str, markdown: str) -> str:
        raw = f"{scene}|{target_code}|{markdown}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

