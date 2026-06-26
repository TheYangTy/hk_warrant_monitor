from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from argparse import Namespace
from datetime import datetime
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hk_warrant_monitor.core.enums import Direction, RiskLevel
from hk_warrant_monitor.infra.config_loader import load_settings
from hk_warrant_monitor.infra.database import Database
from hk_warrant_monitor.infra.logger import setup_logger
from hk_warrant_monitor.watchlist.service import WatchlistService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hk-warrant-monitor")
    subparsers = parser.add_subparsers(dest="command", required=False)

    menu = subparsers.add_parser("menu", help="Open interactive menu")
    menu.set_defaults(func=cmd_menu)

    init_db = subparsers.add_parser("init-db", help="Initialize SQLite database")
    init_db.set_defaults(func=cmd_init_db)

    watchlist = subparsers.add_parser("watchlist", help="Manage underlying watchlist")
    watch_sub = watchlist.add_subparsers(dest="watch_command", required=True)

    add = watch_sub.add_parser("add", help="Add or update an underlying")
    add.add_argument("code")
    add.add_argument("--name", default="")
    add.add_argument("--direction", choices=[v.value for v in Direction], default=Direction.LONG.value)
    add.add_argument("--risk-level", choices=[v.value for v in RiskLevel], default=RiskLevel.MEDIUM.value)
    add.add_argument("--allow-overnight", action="store_true")
    add.add_argument("--disabled", action="store_true")
    add.set_defaults(func=cmd_watchlist_add)

    add_interactive = watch_sub.add_parser("add-interactive", help="Interactively add or update an underlying")
    add_interactive.set_defaults(func=cmd_watchlist_add_interactive)

    remove = watch_sub.add_parser("remove", help="Remove an underlying")
    remove.add_argument("code")
    remove.set_defaults(func=cmd_watchlist_remove)

    remove_interactive = watch_sub.add_parser("remove-interactive", help="Interactively remove an underlying")
    remove_interactive.set_defaults(func=cmd_watchlist_remove_interactive)

    enable = watch_sub.add_parser("enable", help="Enable monitoring for an underlying")
    enable.add_argument("code")
    enable.set_defaults(func=cmd_watchlist_enable)

    disable = watch_sub.add_parser("disable", help="Disable monitoring for an underlying")
    disable.add_argument("code")
    disable.set_defaults(func=cmd_watchlist_disable)

    list_cmd = watch_sub.add_parser("list", help="List watchlist")
    list_cmd.add_argument("--enabled-only", action="store_true")
    list_cmd.set_defaults(func=cmd_watchlist_list)

    scan = subparsers.add_parser("scan", help="Run market scan")
    scan.add_argument("--once", action="store_true", help="Run one scan and exit")
    scan.add_argument("--mock", action="store_true", help="Use development mock market data instead of Futu OpenD")
    scan.set_defaults(func=cmd_scan)

    position = subparsers.add_parser("position", help="Manage warrant/CBBC positions")
    position_sub = position.add_subparsers(dest="position_command", required=True)

    pos_add = position_sub.add_parser("add", help="Add a warrant/CBBC position")
    pos_add.add_argument("product_code")
    pos_add.add_argument("--buy-price", type=float, required=True)
    pos_add.add_argument("--quantity", type=int, required=True)
    pos_add.add_argument("--buy-time", default="")
    pos_add.set_defaults(func=cmd_position_add)

    pos_list = position_sub.add_parser("list", help="List positions")
    pos_list.add_argument("--all", action="store_true", help="Include closed positions")
    pos_list.set_defaults(func=cmd_position_list)

    pos_close = position_sub.add_parser("close", help="Close a position record")
    pos_close.add_argument("id", type=int)
    pos_close.set_defaults(func=cmd_position_close)

    pos_delete = position_sub.add_parser("delete", help="Delete a position record")
    pos_delete.add_argument("id", type=int)
    pos_delete.set_defaults(func=cmd_position_delete)

    pos_analyze = position_sub.add_parser("analyze", help="Analyze open positions")
    pos_analyze.add_argument("--mock", action="store_true", help="Use development mock prices instead of Futu OpenD")
    pos_analyze.set_defaults(func=cmd_position_analyze)

    notify = subparsers.add_parser("notify", help="Notification tools")
    notify_sub = notify.add_subparsers(dest="notify_command", required=True)
    notify_test = notify_sub.add_parser("test-feishu", help="Send a Feishu test message")
    notify_test.set_defaults(func=cmd_notify_test_feishu)

    ai = subparsers.add_parser("ai", help="AI analysis tools")
    ai_sub = ai.add_subparsers(dest="ai_command", required=True)
    ai_usage = ai_sub.add_parser("usage", help="Show today's AI usage")
    ai_usage.set_defaults(func=cmd_ai_usage)

    web = subparsers.add_parser("web", help="Start local web dashboard")
    web.add_argument("--host", default="0.0.0.0")
    web.add_argument("--port", type=int, default=8765)
    web.set_defaults(func=cmd_web)
    return parser


def bootstrap():
    settings = load_settings()
    logger = setup_logger()
    db = Database(settings["database"]["path"])
    db.init()
    return settings, logger, db


def safe_input(prompt: str) -> str:
    print(prompt, end="", flush=True)
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return input().strip()

    raw = buffer.readline()
    encodings = [sys.stdin.encoding, "utf-8", "gb18030", "big5", "mac_roman"]
    for encoding in [item for item in encodings if item]:
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def ensure_runtime_dependencies() -> None:
    """Let direct PyCharm runs work before this project's venv is fully installed."""
    missing = [name for name in ("futu", "requests") if importlib.util.find_spec(name) is None]
    if not missing:
        return

    reference_site_packages = Path(
        "/Users/marcus/Desktop/dev/large_stock_options_monitor/.venv/lib/python3.13/site-packages"
    )
    if reference_site_packages.exists():
        sys.path.append(str(reference_site_packages))


def cmd_init_db(_args) -> int:
    _, logger, db = bootstrap()
    logger.info("Database initialized at %s", db.path)
    return 0


def cmd_watchlist_add(args) -> int:
    _, logger, db = bootstrap()
    service = WatchlistService(db)
    item = service.add(
        args.code,
        args.name,
        Direction(args.direction),
        RiskLevel(args.risk_level),
        args.allow_overnight,
        enable=not args.disabled,
    )
    logger.info("Saved watch item: %s %s %s %s", item.code, item.name, item.direction.value, item.risk_level.value)
    return 0


def cmd_watchlist_add_interactive(_args) -> int:
    _, logger, db = bootstrap()
    service = WatchlistService(db)
    prompt_add_watch_item(service, logger)
    return 0


def prompt_add_watch_item(service: WatchlistService, logger) -> None:
    code = safe_input("股票代码，例如 00700.HK 或 HK.00700: ")
    name = safe_input("股票名称，例如 腾讯控股: ")
    direction_raw = safe_input("方向 LONG=只看买购/牛证，SHORT=只看买沽/熊证，BOTH=多空都看，默认 LONG: ").upper() or Direction.LONG.value
    risk_raw = safe_input("风险 LOW/MEDIUM/HIGH，默认 MEDIUM: ").upper() or RiskLevel.MEDIUM.value
    overnight_raw = safe_input("是否允许隔夜 y/N，默认 N: ").lower()
    item = service.add(
        code,
        name,
        Direction(direction_raw),
        RiskLevel(risk_raw),
        allow_overnight=overnight_raw in {"y", "yes", "true", "1"},
        enable=True,
    )
    logger.info("Saved watch item: %s %s %s %s", item.code, item.name, item.direction.value, item.risk_level.value)


def cmd_watchlist_remove(args) -> int:
    _, logger, db = bootstrap()
    WatchlistService(db).remove(args.code)
    logger.info("Removed watch item: %s", args.code)
    return 0


def cmd_watchlist_remove_interactive(_args) -> int:
    _, logger, db = bootstrap()
    service = WatchlistService(db)
    items = service.list()
    if items:
        print("当前关注列表:")
        for item in items:
            print(f"- {item.code}\t{item.name}\t{item.direction.value}\t{item.risk_level.value}")
    code = safe_input("请输入要删除的股票代码，例如 HK.00700: ")
    service.remove(code)
    logger.info("Removed watch item: %s", code)
    return 0


def cmd_watchlist_enable(args) -> int:
    _, logger, db = bootstrap()
    WatchlistService(db).set_enabled(args.code, True)
    logger.info("Enabled watch item: %s", args.code)
    return 0


def cmd_watchlist_disable(args) -> int:
    _, logger, db = bootstrap()
    WatchlistService(db).set_enabled(args.code, False)
    logger.info("Disabled watch item: %s", args.code)
    return 0


def cmd_watchlist_list(args) -> int:
    _, _logger, db = bootstrap()
    items = WatchlistService(db).list(enabled_only=args.enabled_only)
    if not items:
        print("No watch items. Add one with: hk-warrant-monitor watchlist add 00700.HK --name 腾讯控股")
        return 0
    for item in items:
        status = "ENABLED" if item.enable else "DISABLED"
        overnight = "overnight" if item.allow_overnight else "intraday"
        print(f"{item.code}\t{item.name}\t{item.direction.value}\t{item.risk_level.value}\t{overnight}\t{status}")
    return 0


def cmd_scan(args) -> int:
    ensure_runtime_dependencies()
    from hk_warrant_monitor.jobs.intraday_scan_job import IntradayScanJob
    from hk_warrant_monitor.notifications.feishu_client import FeishuClient
    from hk_warrant_monitor.notifications.push_service import PushService

    settings, logger, db = bootstrap()
    if args.mock:
        from hk_warrant_monitor.data_sources.mock_client import MockQuoteClient

        futu = MockQuoteClient()
    else:
        from hk_warrant_monitor.data_sources.futu_client import FutuQuoteClient

    futu = FutuQuoteClient(settings["futu"]["host"], settings["futu"]["port"], logger)
    watchlist = WatchlistService(db)
    if not ensure_watchlist_before_scan(watchlist, logger):
        return 0
    feishu = FeishuClient(settings["feishu"]["webhook_url"], settings["feishu"]["secret"])
    push_service = PushService(db, feishu, logger)
    job = IntradayScanJob(settings, db, futu, watchlist, push_service, logger)
    try:
        if args.once:
            signals = job.run_once()
            for signal in signals:
                print(
                    f"{signal.underlying_code}\t{signal.action.value}\t"
                    f"confidence={signal.confidence}\tproduct={signal.product_code or '-'}\t{signal.reason}"
                )
            return 0

        interval = int(settings["scan"]["interval_seconds"])
        dashboard = start_web_dashboard_for_scan(logger)
        send_monitor_started_push(push_service, watchlist, interval, dashboard)
        logger.info("Starting continuous scan. interval=%ss", interval)
        while True:
            try:
                job.run_once()
            except Exception as exc:
                db.set_state("last_scan_status", f"error: {exc}")
                logger.exception("Scan iteration failed; will retry after %ss", interval)
            time.sleep(interval)
    finally:
        futu.close()


def ensure_watchlist_before_scan(watchlist: WatchlistService, logger) -> bool:
    if watchlist.list(enabled_only=True):
        return True
    print("当前没有启用的关注股票。")
    if not sys.stdin.isatty():
        logger.info("Watchlist is empty. Add symbols with `watchlist add` first.")
        return False
    answer = safe_input("是否现在添加关注股票？输入 y 添加，其他键退出扫描: ").lower()
    if answer not in {"y", "yes"}:
        return False
    prompt_add_watch_item(watchlist, logger)
    return bool(watchlist.list(enabled_only=True))


def start_web_dashboard_for_scan(logger) -> dict[str, object] | None:
    try:
        from hk_warrant_monitor.web.server import start_web_server_background

        return start_web_server_background(host="0.0.0.0", port=8765)
    except OSError as exc:
        logger.warning("Web dashboard was not started automatically: %s", exc)
        return None


def send_monitor_started_push(
    push_service: PushService,
    watchlist: WatchlistService,
    interval: int,
    dashboard: dict[str, object] | None = None,
) -> None:
    from hk_warrant_monitor.core.enums import PushLevel

    items = watchlist.list(enabled_only=True)
    item_lines = "\n".join(
        f"- {item.name or item.code} ({item.code}) 方向:{item.direction.value} 风险:{item.risk_level.value}"
        for item in items
    )
    if not item_lines:
        item_lines = "- 暂无启用关注股票"
    dashboard_text = ""
    if dashboard:
        lan_urls = dashboard.get("lan") or []
        if isinstance(lan_urls, str):
            lan_urls = [lan_urls]
        lan_lines = "\n".join(f"- 手机/iPad: {url}" for url in lan_urls)
        if not lan_lines:
            lan_lines = "- 手机/iPad: 未发现局域网地址，请检查 Wi-Fi/防火墙"
        dashboard_text = f"\n\nWeb 看板:\n- 本机: {dashboard['local']}\n{lan_lines}"
    push_service.push(
        PushLevel.INFO,
        "monitor_started",
        "SYSTEM",
        "港股窝轮监控已开始",
        (
            "**港股窝轮/牛熊证监控已开始**\n\n"
            f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"扫描间隔: {interval} 秒\n\n"
            f"关注列表:\n{item_lines}\n\n"
            "系统将以正股趋势为判断依据，筛选合适窝轮/牛熊证作为执行工具。"
            f"{dashboard_text}"
        ),
    )


def cmd_position_add(args) -> int:
    _, logger, db = bootstrap()
    from hk_warrant_monitor.watchlist.position_service import PositionService

    buy_time = args.buy_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    position = PositionService(db).add(args.product_code, args.buy_price, args.quantity, buy_time)
    logger.info(
        "Saved position: id=%s product=%s buy_price=%.4f quantity=%s buy_time=%s",
        position.id,
        position.product_code,
        position.buy_price,
        position.quantity,
        position.buy_time,
    )
    return 0


def cmd_position_list(args) -> int:
    _, _logger, db = bootstrap()
    from hk_warrant_monitor.watchlist.position_service import PositionService

    positions = PositionService(db).list(open_only=not args.all)
    if not positions:
        print("No positions.")
        return 0
    for position in positions:
        print(
            f"{position.id}\t{position.product_code}\tbuy={position.buy_price:.4f}\t"
            f"qty={position.quantity}\t{position.buy_time}\t{position.status}"
        )
    return 0


def cmd_position_close(args) -> int:
    _, logger, db = bootstrap()
    from hk_warrant_monitor.watchlist.position_service import PositionService

    PositionService(db).close(args.id)
    logger.info("Closed position: %s", args.id)
    return 0


def cmd_position_delete(args) -> int:
    _, logger, db = bootstrap()
    from hk_warrant_monitor.watchlist.position_service import PositionService

    PositionService(db).delete(args.id)
    logger.info("Deleted position: %s", args.id)
    return 0


def cmd_position_analyze(args) -> int:
    settings, _logger, db = bootstrap()
    from hk_warrant_monitor.strategy.position_engine import PositionEngine
    from hk_warrant_monitor.watchlist.position_service import PositionService

    if args.mock:
        from hk_warrant_monitor.data_sources.mock_client import MockQuoteClient

        quote = MockQuoteClient()
    else:
        from hk_warrant_monitor.data_sources.futu_client import FutuQuoteClient

        quote = FutuQuoteClient(settings["futu"]["host"], settings["futu"]["port"])

    try:
        positions = PositionService(db).list(open_only=True)
        if not positions:
            print("No open positions.")
            return 0
        engine = PositionEngine(settings)
        for position in positions:
            current_price = quote.get_product_price(position.product_code)
            result = engine.analyze(position, current_price)
            print(
                f"{position.id}\t{position.product_code}\tprice={current_price:.4f}\t"
                f"pnl={result.pnl_amount:.2f}\tpnl_ratio={result.pnl_ratio:.1f}%\t"
                f"action={result.action.value}\t{result.reason}"
            )
        return 0
    finally:
        quote.close()


def cmd_notify_test_feishu(_args) -> int:
    ensure_runtime_dependencies()
    settings, logger, db = bootstrap()
    from hk_warrant_monitor.core.enums import PushLevel
    from hk_warrant_monitor.notifications.feishu_client import FeishuClient
    from hk_warrant_monitor.notifications.push_service import PushService

    feishu = FeishuClient(settings["feishu"]["webhook_url"], settings["feishu"]["secret"])
    service = PushService(db, feishu, logger)
    sent = service.push(
        PushLevel.INFO,
        "manual_feishu_test",
        "SYSTEM",
        "港股窝轮监控测试",
        f"**飞书推送测试**\n\nPyCharm 配置已生效，机器人连通性正常。\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    )
    print(f"sent={sent}")
    return 0


def cmd_ai_usage(_args) -> int:
    settings, _logger, db = bootstrap()
    row = db.fetchone(
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
    limit = settings.get("ai", {}).get("daily_limit", 50)
    calls = int(row["calls"]) if row else 0
    prompt_tokens = int(row["prompt_tokens"]) if row else 0
    completion_tokens = int(row["completion_tokens"]) if row else 0
    total_tokens = int(row["total_tokens"]) if row else 0
    print(f"AI 今日调用: {calls}/{limit}")
    print(f"输入 tokens: {prompt_tokens}")
    print(f"输出 tokens: {completion_tokens}")
    print(f"合计 tokens: {total_tokens}")
    return 0


def cmd_web(args) -> int:
    ensure_runtime_dependencies()
    from hk_warrant_monitor.web.server import run_web_server

    run_web_server(host=args.host, port=args.port)
    return 0


def cmd_menu(_args=None) -> int:
    while True:
        print("\n港股窝轮/牛熊证监控")
        print("1. 添加关注股票")
        print("2. 删除关注股票")
        print("3. 查看关注列表")
        print("4. 真实扫描一次并发送飞书")
        print("5. 开始真实持续扫描")
        print("6. 测试飞书推送")
        print("7. Mock扫描一次（不需要OpenD）")
        print("8. 分析持仓")
        print("9. 查看今日AI用量")
        print("10. 启动Web看板")
        print("0. 退出")
        choice = safe_input("请选择: ")

        if choice == "1":
            cmd_watchlist_add_interactive(None)
        elif choice == "2":
            cmd_watchlist_remove_interactive(None)
        elif choice == "3":
            cmd_watchlist_list(Namespace(enabled_only=False))
        elif choice == "4":
            return cmd_scan(Namespace(once=True, mock=False))
        elif choice == "5":
            print("开始持续扫描。停止时点 PyCharm 红色 Stop 按钮，或在终端按 Ctrl+C。")
            return cmd_scan(Namespace(once=False, mock=False))
        elif choice == "6":
            cmd_notify_test_feishu(None)
        elif choice == "7":
            return cmd_scan(Namespace(once=True, mock=True))
        elif choice == "8":
            cmd_position_analyze(Namespace(mock=False))
        elif choice == "9":
            cmd_ai_usage(None)
        elif choice == "10":
            print("启动 Web 看板。停止时点 PyCharm 红色 Stop 按钮，或在终端按 Ctrl+C。")
            return cmd_web(Namespace(host="0.0.0.0", port=8765))
        elif choice == "0":
            return 0
        else:
            print("无效选择，请重新输入。")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        return cmd_menu(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
