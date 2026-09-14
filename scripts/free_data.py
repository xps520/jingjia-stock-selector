#!/usr/bin/env python3
"""free_data.py — 免费行情数据源（腾讯主力 + 东财补充），替代 Tushare。

设计原则（实测 2026-09-14）：
  · 腾讯 qt.gtimg.cn / web.ifzq.gtimg.cn —— 零风控、Python 直连稳定，作为主力。
  · 东财 push2 家族 —— 字段全但风控严（密集请求会封出口IP），仅用于
    「涨停池」这类低频、东财独有的数据；请求间做节流与重试。

数据口径（实测验证）：
  · 集合竞价 9:25 撮合成交会并入当日分时「09:30 首条」：
      竞价价 = 首条价 = 今开；竞价量/额 = 首条累计量/额。
  · 腾讯分时首条格式： "0930 10.80 1620 1749600.00"（时间 价 累计量手 累计额元）
  · 腾讯快照（GBK，~分隔）：第4位昨收、第5位今开、第3位最新价。
  · 东财涨停池：ltsz/amount/fund 单位均为「元」，与 Tushare limit_list_d 对齐。

代码格式：腾讯 sh/sz/bj 前缀；东财 secid 沪=1.xxxxxx 深/北=0.xxxxxx。
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime

# 腾讯需要 Referer 才稳；东财对 python 默认 UA 会断连，需伪装浏览器
_TX_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://gu.qq.com/",
}
_EM_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://quote.eastmoney.com/",
}
EM_UT = "7eea3edcaed734bea9cbfc24409ed989"


# ---------------- 基础 HTTP ----------------
def _get(url: str, headers: dict, timeout: float = 12.0, retries: int = 3,
         encoding: str = "utf-8") -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(encoding, "replace")
        except Exception as e:      # noqa: BLE001
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def _get_json(url: str, headers: dict, **kw):
    return json.loads(_get(url, headers, **kw))


# ---------------- 代码转换 ----------------
def to_em_code(ts_code: str) -> str:
    return ts_code.split(".")[0] if "." in ts_code else ts_code


def to_ts_code(code: str) -> str:
    code = code.strip()
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def tx_prefix(code: str) -> str:
    code = to_em_code(code)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def secid(code: str) -> str:
    code = to_em_code(code)
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


# ---------------- 交易日历（腾讯指数日K，新域名） ----------------
_TX_KLINE = ("https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
             "?param={sym},day,,,{n},qfq")


def _tx_kline_rows(code: str, n: int = 60) -> list[list]:
    """腾讯前复权日K行 [[日期,开,收,高,低,量,...]]。"""
    raw = _get(_TX_KLINE.format(sym=tx_prefix(code), n=n), _TX_HEADERS)
    d = json.loads(raw)
    node = (d.get("data") or {}).get(tx_prefix(code)) or {}
    return node.get("qfqday") or node.get("day") or []


def trade_days(start: str, end: str) -> list[str]:
    """腾讯上证指数日K日期作为交易日历（YYYYMMDD，升序）。"""
    rows = _tx_kline_rows("000001", 800)
    days = [str(r[0]).replace("-", "") for r in rows]
    return [x for x in days if start <= x <= end]


def latest_trade_day(upto: str | None = None) -> str:
    upto = upto or datetime.now().strftime("%Y%m%d")
    rows = _tx_kline_rows("000001", 30)
    days = [str(r[0]).replace("-", "") for r in rows]
    past = [x for x in days if x <= upto]
    return past[-1] if past else (days[-1] if days else upto)


# ---------------- 涨停池（东财，替代 limit_list_d） ----------------
def zt_pool(trade_date: str, retries: int = 4) -> dict[str, dict]:
    """东财涨停池 → {code6: {...}}，字段对齐 Tushare limit_list_d。

    含：name / limit_times(lbc) / float_mv(ltsz,元) / amount(元)
        / fd_amount(fund,元) / open_times(zbc) / last_time(lbt,HHMMSS)
        / first_time(fbt) / turnover(hs,%) / industry(hybk)
    """
    url = ("https://push2ex.eastmoney.com/getTopicZTPool"
           f"?ut={EM_UT}&dpt=wz.ztzt&Pageindex=0&pagesize=500"
           f"&sort=fbt%3Aasc&date={trade_date}")
    data = _get_json(url, _EM_HEADERS, retries=retries)
    pool = (data.get("data") or {}).get("pool") or []
    out = {}
    for r in pool:
        code = str(r.get("c") or "").strip()
        if not code:
            continue
        out[code] = {
            "code": code,
            "ts_code": to_ts_code(code),
            "name": str(r.get("n") or "").strip(),
            "limit_times": int(r.get("lbc") or 1),
            "float_mv": float(r.get("ltsz") or 0),
            "amount": float(r.get("amount") or 0),
            "fd_amount": float(r.get("fund") or 0),
            "open_times": int(r.get("zbc") or 0),
            "last_time": str(r.get("lbt") or ""),
            "first_time": str(r.get("fbt") or ""),
            "turnover": float(r.get("hs") or 0),
            "industry": str(r.get("hybk") or ""),
        }
    return out


# ---------------- 腾讯分时（含竞价首条） ----------------
def _tx_minutes(code: str) -> list[list[str]]:
    """腾讯分时数据。返回按日期分组的 [{date, bars:[...]}]。"""
    raw = _get(f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={tx_prefix(code)}",
               _TX_HEADERS)
    d = json.loads(raw)
    node = (d.get("data") or {}).get(tx_prefix(code)) or {}
    return node.get("data") or []


def _auction_from_bars(bars: list[str]) -> tuple[float, float, float] | None:
    """从分时 bars 首条解析 (竞价价, 竞价量手, 竞价额元)。"""
    if not bars:
        return None
    p = bars[0].split()
    if len(p) < 4:
        return None
    try:
        return float(p[1]), float(p[2]), float(p[3])
    except (ValueError, IndexError):
        return None


def auction_one(code: str, trade_date: str | None = None) -> tuple | None:
    """单只竞价数据 → (price, gap_pct, amount元)。

    trade_date 为空取最新交易日；指定时从腾讯分时里找该日（近5日窗口）。
    """
    try:
        groups = _tx_minutes(code)
    except Exception:               # noqa: BLE001
        return None
    if not groups:
        return None

    bars = None
    if trade_date:
        for g in groups:
            gd = str(g.get("date") or "")
            if gd == trade_date:
                bars = g.get("data") or []
                break
        if bars is None:
            return None
    else:
        # 腾讯返回的日期是倒序（最新在前），必须按日期排序后取最新一天
        newest = max(groups, key=lambda g: str(g.get("date") or ""))
        bars = newest.get("data") or []

    a = _auction_from_bars(bars)
    if not a:
        return None
    price, _vol, amount = a

    pre_close = prev_close(code, trade_date)
    if not pre_close or pre_close <= 0:
        return None
    gap = (price / pre_close - 1) * 100
    return price, gap, amount


def auction_batch(codes: list[str], trade_date: str | None = None,
                  pause: float = 0.05, progress: bool = True) -> dict[str, tuple]:
    """批量竞价数据 → {code6: (price, gap, amount)}。"""
    out = {}
    total = len(codes)
    for i, c in enumerate(codes, 1):
        try:
            r = auction_one(c, trade_date)
            if r:
                out[c] = r
        except Exception as e:      # noqa: BLE001
            if progress:
                print(f"    [竞价] {c} 取数失败({type(e).__name__})，跳过")
        if pause:
            time.sleep(pause)
        if progress and i % 25 == 0:
            print(f"    [竞价] 进度 {i}/{total}")
    return out


# ---------------- 昨收 ----------------
def prev_close(code: str, trade_date: str | None = None) -> float:
    """昨收：指定日期时取该日前一根日K收盘；否则用腾讯快照昨收。"""
    if trade_date:
        rows = _tx_kline_rows(code, 30)
        days = [(str(r[0]).replace("-", ""), r[2]) for r in rows]
        past = [x for x in days if x[0] < trade_date]
        return float(past[-1][1]) if past else 0.0
    snap = tx_snapshot([code])
    return (snap.get(to_em_code(code)) or {}).get("pre_close", 0.0)


# ---------------- 日线收盘（替代 daily） ----------------
def close_one(code: str, trade_date: str) -> float | None:
    rows = _tx_kline_rows(code, 60)
    for r in rows:
        if str(r[0]).replace("-", "") == trade_date:
            return float(r[2])
    return None


def close_batch(codes: list[str], trade_date: str, pause: float = 0.05) -> dict[str, float]:
    out = {}
    for c in codes:
        try:
            v = close_one(c, trade_date)
            if v is not None:
                out[c] = v
        except Exception:           # noqa: BLE001
            pass
        if pause:
            time.sleep(pause)
    return out


# ---------------- 腾讯实时快照 ----------------
def tx_snapshot(codes: list[str]) -> dict[str, dict]:
    """腾讯批量快照 → {code6: {name,price,pre_close,open,volume_hand,time}}。"""
    if not codes:
        return {}
    q = ",".join(tx_prefix(c) for c in codes)
    raw = _get(f"https://qt.gtimg.cn/q={q}", _TX_HEADERS, encoding="gbk")
    out = {}
    for line in raw.split(";"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        body = line.split('="', 1)[1].rstrip('"')
        f = body.split("~")
        if len(f) < 6:
            continue

        def _n(i):
            try:
                return float(f[i])
            except (IndexError, ValueError):
                return 0.0

        out[f[2]] = {
            "code": f[2], "name": f[1], "price": _n(3),
            "pre_close": _n(4), "open": _n(5),
            "volume_hand": _n(6), "time": f[30] if len(f) > 30 else "",
        }
    return out
