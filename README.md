# 港股窝轮/牛熊证 AI 交易辅助系统

独立项目，目标是以港股正股趋势和风险判断为核心，以窝轮/牛熊证作为执行工具，提供实时监控、信号分析和飞书推送。

## 核心原则

- 自选正股由用户主动新增、删除、修改，不在业务代码中写死。
- 买卖信号主要基于正股行情、K线、指标、盘口和指数联动。
- 窝轮/牛熊证只作为执行工具筛选，不直接用产品价格波动反推交易方向。
- 系统只做辅助提醒，不自动交易。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

新增自选股：

```bash
hk-warrant-monitor watchlist add 00700.HK --name 腾讯控股 --direction LONG --risk-level MEDIUM
```

查看自选股：

```bash
hk-warrant-monitor watchlist list
```

单次扫描：

```bash
hk-warrant-monitor scan --once
```

开发环境无 Futu OpenD 时，可用 mock 数据验证链路：

```bash
hk-warrant-monitor scan --once --mock
```

`--mock` 只生成开发测试行情和测试窝轮，不会自动新增自选股；真实运行必须由用户先主动加入正股。

录入窝轮/牛熊证持仓：

```bash
hk-warrant-monitor position add 12345.HK --buy-price 0.18 --quantity 100000 --buy-time "2026-06-24 10:30:00"
```

分析持仓：

```bash
hk-warrant-monitor position analyze
```

开发测试可用：

```bash
hk-warrant-monitor position analyze --mock
```

## PyCharm 运行

项目已内置 PyCharm Run Configurations。用 PyCharm 打开本目录后，右上角运行下拉框可以直接选择：

- `00 主菜单`
- `01 添加关注股票（交互）`
- `02 删除关注股票（交互）`
- `03 查看关注列表`
- `04 真实扫描一次（发送飞书）`
- `05 真实持续扫描（发送飞书）`
- `06 测试飞书推送`
- `07 Mock扫描一次（不需要OpenD）`
- `08 运行单元测试`
- `09 分析持仓`
- `10 启动Web看板`

添加关注股票时运行 `01 添加关注股票（交互）`，在 PyCharm 控制台按提示输入即可，例如：

```text
股票代码，例如 00700.HK 或 HK.00700: 00700.HK
股票名称，例如 腾讯控股: 腾讯控股
方向 LONG/SHORT/BOTH，默认 LONG: LONG
风险 LOW/MEDIUM/HIGH，默认 MEDIUM: MEDIUM
是否允许隔夜 y/N，默认 N: N
```

真实扫描前请确认 Futu OpenD 已启动，且 `.env` 已配置飞书机器人。

选择 `05 真实持续扫描（发送飞书）` 或菜单里的 `5. 开始真实持续扫描` 时，会自动在后台启动 Web 看板，并在飞书“监控已开始”通知里附上本机和手机/iPad访问地址。

## Web 看板

启动：

```bash
python src/hk_warrant_monitor/main.py web
```

或在 PyCharm 里选择：

```text
10 启动Web看板
```

电脑访问：

```text
http://127.0.0.1:8765
```

手机/iPad 和电脑在同一个 Wi-Fi 下时，运行日志会显示类似：

```text
LAN dashboard URL: http://192.168.x.x:8765
```

手机浏览器打开这个地址即可管理关注列表、查看 AI token 用量、最近信号和日志。

也可以直接运行 `src/hk_warrant_monitor/main.py`，不填参数时会进入主菜单：

```text
1. 添加关注股票
2. 删除关注股票
3. 查看关注列表
4. 真实扫描一次并发送飞书
5. 开始真实持续扫描
6. 测试飞书推送
7. Mock扫描一次（不需要OpenD）
8. 分析持仓
0. 退出
```
