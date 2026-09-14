# 竞价选股（云端）· jingjia-stock-selector

A股 **9:25 集合竞价选股**（v5-Top3 策略），**免费数据源**（腾讯 + 东方财富），
云端 GitHub Actions 自动运行 + **微信（Server酱）推送**，无需本机开机。

## 云端自动运行

- **仓库**：https://github.com/xps520/jingjia-stock-selector
- **调度**：工作日北京时间 **9:31 / 9:33 / 9:35**（跑三次容错）
- **通知**：结果自动推送到微信（Server酱）

> ⚠️ 调度为何是 9:31 而非 9:25：免费源的「竞价成交额」取自腾讯分时
> **09:30 首条**（集合竞价成交并入该分钟），9:30 开盘后才生成。
> 原 Tushare 版可在 9:25 跑，免费源做不到——这是数据源的固有限制。

## 数据源

| 数据 | 来源 | 说明 |
|:---|:---|:---|
| 昨日涨停池 | 东财 `push2ex` | 连板/流通市值/成交额/封单额/开板次数/最后封板时间 |
| 集合竞价 | 腾讯 `day/query` | 竞价价=09:30首条价（9:25撮合价）；竞价额=首条累计额 |
| 日K/收盘/交易日历 | 腾讯 `newfqkline` | 前复权 |
| 实时快照 | 腾讯 `qt.gtimg.cn` | 昨收/今开，零风控 |

**无需任何 Token / 账号**，仅用 Python 标准库。

## 本机使用

双击 `RUN_DAILY.bat`（每日选股）或 `RUN_BACKTEST.bat`（近19日回测）。

命令行：

```bash
cd scripts
python run_daily.py --date 20260911    # 指定日期
python run_daily.py                     # 最近交易日
python run_backtest.py --quick          # 快速回测
```

推送需设环境变量：`set SERVERCHAN_SENDKEY=SCTxxxx`（Windows）。

## 手动触发云端

GitHub 仓库 → Actions → 竞价选股（云端）→ Run workflow（可填日期）。

## 文件结构

```text
├── .github/workflows/jingjia.yml   # 云端调度
├── scripts/
│   ├── free_data.py                # 免费数据源模块
│   ├── notify.py                   # Server酱微信推送
│   ├── run_daily.py                # 每日选股
│   └── run_backtest.py             # 回测
├── RUN_DAILY.bat / RUN_BACKTEST.bat
├── README.md / SKILL.md
```

## 已知限制

- **无 9:20–9:25 竞价过程价**：只有 9:25 撮合价（今开）
- **回测窗口受限**：腾讯分时仅存近 5 个交易日 → 竞价额仅近端可用，长周期回测需 Tushare
- **东财风控**：涨停池接口密集请求会封出口 IP，已内置节流与重试

## 免责声明

仅用于个人研究、策略复盘，不构成任何投资建议。短线交易风险高，请自行判断。
