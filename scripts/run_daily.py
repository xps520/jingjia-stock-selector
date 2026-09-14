#!/usr/bin/env python3
"""v5-Top3竞价选股 — 每日运行脚本（免费数据源版）

用法: python run_daily.py --date 20260911
      python run_daily.py            # 默认取最近交易日

数据源：腾讯（主力，零风控）+ 东方财富（涨停池）
        —— 已完全移除 Tushare 依赖。

口径说明（实测 2026-09-14 验证）：
  · 昨日涨停池（东财）提供：连板数/流通市值/成交额/封单额/开板次数/最后封板时间
  · 今日竞价（腾讯分时 09:30 首条）：竞价价 = 今开，竞价额 = 首条累计成交额
    注意：免费源没有「9:20-9:25 竞价过程价」，竞价价以 9:25 撮合价（今开）为准。
"""
import argparse
import sys
import time

import free_data as fd


def fetch_with_retry(fn, name, max_retries=4, base_wait=3):
    """带重试的数据获取，适用于 9:25 后数据延迟的场景。"""
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            if result:
                return result
            if attempt < max_retries:
                wait = base_wait * (1.5 ** (attempt - 1))
                print(f"  ⏳ {name}数据为空，{wait:.0f}秒后重试 ({attempt}/{max_retries})...")
                time.sleep(wait)
        except Exception as e:      # noqa: BLE001
            if attempt < max_retries:
                wait = base_wait * (1.5 ** (attempt - 1))
                print(f"  ⚠️ {name}请求失败: {e}, {wait:.0f}秒后重试 ({attempt}/{max_retries})...")
                time.sleep(wait)
            else:
                print(f"  ❌ {name}请求最终失败: {e}")
    return None


def get_recent_days(target_date=None):
    """获取最近交易日（腾讯指数日K作为交易日历）。"""
    from datetime import datetime
    end = target_date or datetime.now().strftime("%Y%m%d")
    start = "20260101" if target_date else end[:4] + "0101"
    cal = fd.trade_days(start, end)
    if not cal:
        return []
    if target_date and target_date in cal:
        idx = cal.index(target_date)
        return cal[max(0, idx - 2):idx + 1]
    return cal[-5:]


def main():
    parser = argparse.ArgumentParser(description="v5竞价选股（免费数据源）")
    parser.add_argument("--date", type=str, help="目标日期 YYYYMMDD")
    args = parser.parse_args()

    days = get_recent_days(args.date)
    if not days:
        print("❌ 无法获取交易日历")
        sys.exit(1)
    target = args.date or days[-1]
    prev_idx = days.index(target) - 1 if target in days else -1

    if prev_idx < 0:
        print(f"❌ 日期 {target} 无前一日数据")
        sys.exit(1)

    prev = days[prev_idx]
    print(f"📊 竞价选股: {target} (前一日 {prev})")
    print("  📡 数据源: 腾讯(竞价/快照) + 东方财富(涨停池)")

    # ---------- 昨日涨停池 ----------
    print("  获取昨日涨停数据...")
    prev_zt = fetch_with_retry(lambda: fd.zt_pool(prev), "昨日涨停")
    if not prev_zt:
        print("  ❌ 无法获取昨日涨停数据，终止")
        sys.exit(1)
    print(f"  ✅ 昨日涨停 {len(prev_zt)} 只")

    # ---------- 今日竞价 ----------
    print("  获取今日竞价数据（等待数据更新）...")
    codes = list(prev_zt.keys())
    today_auction = fetch_with_retry(
        lambda: fd.auction_batch(codes, target, progress=False),
        "竞价", max_retries=6, base_wait=4,
    )
    if not today_auction:
        print("  ❌ 竞价数据多次重试后仍为空，可能今日非交易日或接口异常")
        sys.exit(1)
    print(f"  ✅ 竞价数据获取成功 ({len(today_auction)}只)")

    auc_map = {c: (p, gap, amt) for c, (p, gap, amt) in today_auction.items()}

    # ---------- 评分 ----------
    zt_set = set(prev_zt.keys())
    print(f"  候选池: {len(zt_set)}只")

    cand = []
    for code, r in prev_zt.items():
        name = r["name"]
        if "ST" in name or code.startswith(("4", "8", "9")):   # 排除北交所
            continue
        mv = r["float_mv"] / 1e8 if r["float_mv"] else 0
        if mv < 20:
            continue
        if code not in auc_map:
            continue

        buy_p, gap, auc_amt = auc_map[code]
        if gap < -3:
            continue
        vr = auc_amt / (mv * 1e8) * 100
        if vr < 0.05:
            continue

        lt = int(r.get("limit_times", 1))
        pa = r.get("amount", 0) or 0
        fa = r.get("fd_amount", 0) or 0
        ot = int(r.get("open_times", 0) or 0)
        ls = str(r.get("last_time", ""))
        lr = fa / pa * 100 if pa > 0 else 0
        if lr < 5:
            continue

        is_lb = ot >= 2 or (ls and ls != "nan" and ls.isdigit() and int(ls) > 143000)

        # v5 评分
        if mv > 200:
            a = 5 if vr >= 0.5 else 4 if vr >= 0.3 else 4 if vr >= 0.2 else 3 if vr >= 0.1 else 2
        else:
            a = 5 if vr >= 0.5 else 4 if vr >= 0.3 else 3 if vr >= 0.2 else 2 if vr >= 0.1 else 1
        if vr > 1.0:
            a -= 0.5

        if 8 <= gap < 10:
            b = 5
        elif gap >= 10:
            b = 4.5
        elif 3 <= gap < 8:
            b = 4
        elif gap >= 1:
            b = 3
        elif gap >= -0.5:
            b = 3
        else:
            b = 2

        c_s = 4.5 if lt == 3 else 4 if lt == 2 else 2.5 if lt == 1 else 2
        d_s = 4

        if lt >= 2 and gap >= 6 and vr > 0.3:
            e = 5 if not is_lb else 4
        elif lt >= 2 and gap >= 4:
            e = 4 if not is_lb else 3
        elif lt >= 2 and gap >= 1:
            e = 2
        elif lt >= 2:
            e = 2
        elif lt == 1 and gap >= 6:
            e = 3
        elif lt == 1 and gap >= 3:
            e = 2.5
        elif lt == 1 and gap >= 1:
            e = 2
        else:
            e = 2

        risk = 0
        if lr < 10:
            risk += 2
        elif lr < 30:
            risk += 1.5
        elif lr < 50:
            risk += 0.5
        if lt >= 4:
            risk += 2
        if lt >= 3 and gap < 2:
            risk += 1
        if mv >= 500:
            risk -= 1
        elif mv >= 200:
            risk -= 0.5
        if is_lb:
            risk += 0.5

        raw = a * 0.25 + b * 0.20 + c_s * 0.15 + d_s * 0.20 + e * 0.20
        score = raw * 4 - risk

        if score >= 16:
            cand.append({
                "name": name, "code": fd.to_ts_code(code), "score": round(score, 1),
                "gap": round(gap, 1), "lt": lt, "vr": round(vr, 3),
                "mv": round(mv, 0), "e": round(e, 1),
            })

    cand.sort(key=lambda x: x["score"], reverse=True)
    top3 = cand[:3]

    # ---------- 组装报告（同时打印与推送） ----------
    lines = []
    max_lt = max((r.get("limit_times", 1) for r in prev_zt.values()), default=1)
    n3 = sum(1 for r in prev_zt.values() if r.get("limit_times") == 3)
    n4 = sum(1 for r in prev_zt.values() if r.get("limit_times") == 4)
    r34 = n4 / n3 * 100 if n3 > 0 else 0

    lines.append("## 一、市场情绪")
    lines.append("| 指标 | 数据 |")
    lines.append("|---:|:---|")
    lines.append(f"| 昨日最高板 | {max_lt}板 |")
    lines.append(f"| 3进4晋级率 | {r34:.0f}% |")

    is_defense = r34 < 20 or max_lt < 3

    if is_defense:
        lines.append("\n## 二、📋 观察池（退潮防守期，不推荐买入）")
    else:
        lines.append(f"\n## 二、🏆 首选买入池 (TOP{len(top3)})")
    lines.append("| 股票 | 代码 | 连板 | 竞开% | 量比% | 评分 |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for c in top3:
        lines.append(f"| {c['name']} | {c['code']} | {c['lt']}板 | "
                     f"{c['gap']:+5.1f}% | {c['vr']:>4.2f}% | {c['score']:>4.1f} |")

    lines.append("\n## 三、最终结论")
    if is_defense:
        lines.append("  🛑 退潮防守期，今日不推荐接力")
        if top3:
            lines.append(f"  可等9:30后承接验证：{'、'.join([c['name'] for c in top3[:3]])}")
    else:
        lines.append("  ✅ 可操作，TOP3评分最高3只")
        if top3:
            best = top3[0]
            lines.append(f"  首选: {best['name']}({best['code']}) {best['score']}分")

    lines.append("\n> ⚠️ 仅策略研究，不构成投资建议")
    lines.append(f"> 📅 {target} · 数据源: 腾讯+东方财富(免费)")

    report = "\n".join(lines)
    print("\n" + report)

    # ---------- 微信推送 ----------
    try:
        from notify import send
        if is_defense:
            title = f"📋 竞价观察 {target}｜退潮防守期"
        elif top3:
            best = top3[0]
            title = f"🏆 竞价选股 {target}｜首选 {best['name']} {best['score']}分"
        else:
            title = f"📭 竞价选股 {target}｜今日无候选"
        send(title, report)
    except Exception as e:          # noqa: BLE001
        print(f"[推送] 异常({type(e).__name__}): {e}")


if __name__ == "__main__":
    main()
