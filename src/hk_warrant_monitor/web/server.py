from __future__ import annotations

import json
import logging
import mimetypes
import socket
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from datetime import datetime

from hk_warrant_monitor.core.enums import Direction, PushLevel, RiskLevel
from hk_warrant_monitor.infra.config_loader import load_settings, project_path
from hk_warrant_monitor.infra.database import Database
from hk_warrant_monitor.infra.logger import setup_logger
from hk_warrant_monitor.notifications.feishu_client import FeishuClient
from hk_warrant_monitor.notifications.push_service import PushService
from hk_warrant_monitor.watchlist.service import WatchlistService, normalize_hk_code


WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = WEB_ROOT / "static"


class DashboardState:
    def __init__(self):
        self.settings = load_settings()
        self.logger = setup_logger()
        self.db = Database(self.settings["database"]["path"])
        self.db.init()
        self.watchlist = WatchlistService(self.db)


class DashboardHandler(BaseHTTPRequestHandler):
    state: DashboardState

    def log_message(self, format, *args):  # noqa: A002
        self.state.logger.debug("web: " + format, *args)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_file(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/")
            self._send_file(STATIC_ROOT / relative)
            return
        if parsed.path == "/api/status":
            self._json(self._status())
            return
        if parsed.path == "/api/watchlist":
            self._json([self._watch_item_payload(item) for item in self.state.watchlist.list()])
            return
        if parsed.path == "/api/ai-usage":
            self._json(self._ai_usage())
            return
        if parsed.path == "/api/signals":
            self._json(self._latest_signals())
            return
        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query)
            limit = int((query.get("limit") or ["120"])[0])
            self._json({"lines": self._log_tail(limit)})
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/watchlist":
            data = self._read_json()
            item = self.state.watchlist.add(
                data["code"],
                data.get("name", ""),
                Direction(data.get("direction", Direction.LONG.value)),
                RiskLevel(data.get("riskLevel", RiskLevel.MEDIUM.value)),
                bool(data.get("allowOvernight", False)),
                bool(data.get("enable", True)),
            )
            self._json(self._watch_item_payload(item), status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/notify/test-feishu":
            self._test_feishu()
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/watchlist/"):
            code = parsed.path.removeprefix("/api/watchlist/")
            data = self._read_json()
            if "enable" in data:
                self.state.watchlist.set_enabled(code, bool(data["enable"]))
                self._json({"ok": True, "code": normalize_hk_code(code), "enable": bool(data["enable"])})
                return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/watchlist/"):
            code = parsed.path.removeprefix("/api/watchlist/")
            self.state.watchlist.remove(code)
            self._json({"ok": True, "code": normalize_hk_code(code)})
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def _status(self) -> dict:
        rows = self.state.db.fetchall("SELECT COUNT(*) AS count FROM watchlist WHERE enable = 1")
        enabled_count = int(rows[0]["count"]) if rows else 0
        last_signal = self.state.db.fetchone("SELECT created_at FROM trade_signal ORDER BY id DESC LIMIT 1")
        runtime_rows = self.state.db.fetchall("SELECT key, value, updated_at FROM runtime_state")
        runtime_state = {row["key"]: {"value": row["value"], "updatedAt": row["updated_at"]} for row in runtime_rows}
        return {
            "app": self.state.settings["app"]["name"],
            "host": self.server.server_address[0],
            "port": self.server.server_address[1],
            "dashboardUrls": dashboard_urls(self.server.server_address[1]),
            "runtimeState": runtime_state,
            "scanInterval": self.state.settings["scan"]["interval_seconds"],
            "futuHost": self.state.settings["futu"]["host"],
            "futuPort": self.state.settings["futu"]["port"],
            "feishuEnabled": bool(self.state.settings["feishu"].get("webhook_url")),
            "aiEnabled": bool(self.state.settings["ai"].get("enabled")),
            "aiModel": self.state.settings["ai"].get("model"),
            "enabledWatchCount": enabled_count,
            "lastSignalAt": last_signal["created_at"] if last_signal else None,
        }

    def _watch_item_payload(self, item) -> dict:
        return {
            "code": item.code,
            "name": item.name,
            "direction": item.direction.value,
            "riskLevel": item.risk_level.value,
            "allowOvernight": item.allow_overnight,
            "enable": item.enable,
        }

    def _ai_usage(self) -> dict:
        row = self.state.db.fetchone(
            """
            SELECT
              COUNT(*) AS calls,
              COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
              COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
              COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM ai_call_record
            WHERE date(created_at, 'localtime') = date('now', 'localtime') AND success = 1
            """
        )
        return {
            "calls": int(row["calls"]) if row else 0,
            "dailyLimit": int(self.state.settings["ai"].get("daily_limit", 50)),
            "promptTokens": int(row["prompt_tokens"]) if row else 0,
            "completionTokens": int(row["completion_tokens"]) if row else 0,
            "totalTokens": int(row["total_tokens"]) if row else 0,
            "model": self.state.settings["ai"].get("model"),
        }

    def _latest_signals(self) -> list[dict]:
        rows = self.state.db.fetchall(
            """
            SELECT underlying_code, product_code, action, confidence, reason, risk, created_at
            FROM trade_signal
            ORDER BY id DESC
            LIMIT 20
            """
        )
        return [dict(row) for row in rows]

    def _log_tail(self, limit: int) -> list[str]:
        log_path = project_path("logs/hk_warrant_monitor.log")
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max(1, min(limit, 500)) :]

    def _test_feishu(self) -> None:
        feishu = FeishuClient(
            self.state.settings["feishu"]["webhook_url"],
            self.state.settings["feishu"]["secret"],
        )
        service = PushService(self.state.db, feishu, self.state.logger)
        ok = service.push(
            level=PushLevel.INFO,
            scene="web_feishu_test",
            target_code="WEB",
            title="港股窝轮看板测试",
            markdown=f"**Web 看板测试**\n\n手机/电脑管理页已连接飞书。\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        )
        self._json({"sent": ok})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        body = path.read_bytes()
        guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or guessed)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status=status)


def _add_unique_ip(ips: list[str], value: str) -> None:
    value = value.strip()
    if not value:
        return
    if value.startswith(("127.", "169.254.")):
        return
    if value not in ips:
        ips.append(value)


def candidate_lan_ips() -> list[str]:
    ips: list[str] = []

    # macOS Wi-Fi is usually en0; wired/adapter interfaces often appear on en1/en2.
    for interface in ("en0", "en1", "en2", "bridge100"):
        try:
            result = subprocess.run(
                ["ipconfig", "getifaddr", interface],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            _add_unique_ip(ips, result.stdout)

    try:
        hostname = socket.gethostname()
        for address in socket.gethostbyname_ex(hostname)[2]:
            _add_unique_ip(ips, address)
    except OSError:
        pass

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add_unique_ip(ips, item[4][0])
    except OSError:
        pass

    return ips


def local_ip() -> str:
    ips = candidate_lan_ips()
    return ips[0] if ips else "127.0.0.1"


def build_web_server(host: str = "0.0.0.0", port: int = 8765) -> tuple[ThreadingHTTPServer, DashboardState]:
    state = DashboardState()
    DashboardHandler.state = state
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    return server, state


def dashboard_urls(port: int) -> dict[str, object]:
    return {
        "local": f"http://127.0.0.1:{port}",
        "lan": [f"http://{ip}:{port}" for ip in candidate_lan_ips()],
    }


def start_web_server_background(host: str = "0.0.0.0", port: int = 8765) -> dict[str, object] | None:
    server, state = build_web_server(host, port)
    urls = dashboard_urls(port)
    thread = threading.Thread(target=server.serve_forever, name="web-dashboard", daemon=True)
    thread.start()
    state.logger.info("Web dashboard started in background: %s", urls["local"])
    for url in urls["lan"]:
        state.logger.info("LAN dashboard URL candidate: %s", url)
    if not urls["lan"]:
        state.logger.warning("No LAN dashboard URL found. Check Wi-Fi and firewall settings.")
    return urls


def run_web_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    server, state = build_web_server(host, port)
    urls = dashboard_urls(port)
    state.logger.info("Web dashboard started: %s", urls["local"])
    for url in urls["lan"]:
        state.logger.info("LAN dashboard URL candidate: %s", url)
    if not urls["lan"]:
        state.logger.warning("No LAN dashboard URL found. Check Wi-Fi and firewall settings.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
