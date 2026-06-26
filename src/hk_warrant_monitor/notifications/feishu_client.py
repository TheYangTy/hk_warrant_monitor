from __future__ import annotations

import base64
import hashlib
import hmac
import time


class FeishuClient:
    def __init__(self, webhook_url: str, secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send_markdown(self, title: str, markdown: str) -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": markdown}],
            },
        }
        if self.secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._sign(timestamp)
        import requests

        response = requests.post(self.webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        body = response.json()
        return body.get("code", body.get("errcode", 0)) == 0

    def _sign(self, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{self.secret}"
        digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")
