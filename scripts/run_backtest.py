#!/usr/bin/env python3
"""v5-Top3竞价选股策略 — 回测验证脚本（免费数据源版）

用法: python run_backtest.py --start 20260801 --end 20260914
      python run_backtest.py --quick  # 快速回测(近19个交易日)

数据源：腾讯（主力）+ 东方财富（涨停池），无 Tushare 依赖。

⚠️ 免费源回测限制（相比 Tushare 版）：
  · 竞价价 = 当日 09:30 首条价（9:25 撮合价），非 9:20-9:25 竞价过程价
  · 腾讯分时只保留近 5 个交易日 → 回测窗口受限于约最近 5 个交易日内的竞价额，
    更早日期只能拿到「竞价价」，竞价额缺失会导致量比维度失效。
  · 因此本回测适合近端快速验证；长周期回测建议仍用 Tushare stk_auction。
"""
import argparse
import sys
import time

import free_data as fd

# 腾讯分时仅保留近5个交易日，回测竞价额受此限制
_TX_INTRADAY_WINDOW = 5


def _quick_days():
    """近 19 个交易日。"""
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    days = fd.trade_days("20260101", today)
    return days[-19:] if len(days) >= 19 else days


def main():
    parser = argparse.ArgumentParser(description="v5竞价选股回测（免费数据源）")
    parser.add_argument("--start", type=str, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, help="结束日期 YYYYMMDD")
    parser.add_argument("--quick", action="store_true", help="快速回测(近19个交易日)")
    args = parser.parse_args()

    if args.quick or args.start is None:
        days = _quick_days()
    else:
        end = args.end or args.start
        days = fd.trade_days(args.start, end)
    days.sort()
    if len(days) < 2:
        print("❌ 可用交易日不足")
        sys.exit(1)

    print(f"📊 回测区间: {days[0]} ~ {days[-1]}（{len(days)}个交易日）")
    print("  📡 数据源: 腾讯 + 东方财富（无 Tushare）")

    # 需要的前置交易日（多取几天用于「前一日涨停池」和股性统计）
    cal_start = fd.trade_days("20260101", days[0])
    pre_days = cal_start[-(30 + len(days)):] if len(cal_start) > len(days) else cal_start
    all_d = sorted(set(pre_days + days))

    # ---------- 涨停池 ----------
    print("  获取历史涨停池...")
    zt_all = {}
    for d in all_d:
        try:
            p = fd.zt_pool(d)
            if p:
                zt_all[d] = p
        except Exception as e:      # noqa: BLE001
            print(f"    [涨停池] {d} 失败({type(e).__name__})")
        time.sleep(0.35)            # 东财节流，避免触发风控
    zt = {d: zt_all[d] for d in days if d in zt_all}
    print(f"  ✅ 涨停池 {len(zt)} 天")

    # ---------- 竞价（仅近端可用） ----------
    print("  获取历史竞价数据（腾讯分时近5日窗口）...")
    auction = {}
    for d in days:
        codes = list(zt.get(d, {}).keys()) or list(zt_all.get(d, {}).keys())
        if not codes:
            continue
        got = fd.auction_batch(codes, d, progress=False)
        for c, (p, gap, amt) in got.items():
            auction[(d, c)] = (p, gap, amt)
        time.sleep(0.2)
    print(f"  ✅ 竞价数据 {len(auction)} 条")

    # ---------- 收盘价 ----------
    print("  获取历史收盘价...")
    closes = {}
    for d in days:
        codes = list(zt_all.get(d, {}).keys())
        for c in codes:
            try:
                v = fd.close_one(c, d)
                if v is not None:
                    closes[(d, c)] = v
            except Exception:       # noqa: BLE001
                pass
    print(f"  ✅ 收盘价 {len(closes)} 条")

    # ---------- 股性 ----------
    zt_by_c = {}
    for d in all_d:
        if d in zt_all:
            for c in zt_all[d]:
                zt_by_c.setdefault(c, set()).add(d)

    def gx(code, ref, n):
        ds = zt_by_c.get(code, set())
        idx = all_d.index(ref)
        w = all_d[max(0, idx - n):idx]
        return sum(1 for d in w if d in ds)

    # ---------- 情绪 ----------
    def get_mood(idx):
        prv = all_d[idx - 1]
        p = zt_all.get(prv)
        if not p:
            return "未知", 0, 0
        ds = {}
        for r in p.values():
            lt = int(r.get("limit_times", 1))
            ds[lt] = ds.get(lt, 0) + 1
        mb = max(ds.keys()) if ds else 0
        n2 = ds.get(2, 0); n3 = ds.get(3, 0); n4 = ds.get(4, 0)
        r23 = n3 / n2 * 100 if n2 > 0 else 0
        r34 = n4 / n3 * 100 if n3 > 0 else 0
        ar = (r23 + r34) / 2
        hs = [r for r in p.values() if int(r.get("limit_times", 1)) == mb] if mb > 0 else []
        hg = []
        td = all_d[idx]
        for r in hs:
            if (td, r["code"]) in auction:
                hg.append(auction[(td, r["code"])][1])
        hn = min(hg) < -5 if hg else False
        if ar < 20 or mb < 3 or hn:
            return "退潮防守期 🛑", ar, mb
        elif ar >= 35 and mb >= 4 and not hn:
            return "接力友好期 ✅", ar, mb
        else:
            return "分歧观察期 ⚡", ar, mb

    # ---------- 回测 ----------
    trades = []
    for i in range(1, len(days)):
        prv = days[i - 1]; tdy = days[i]
        if prv not in zt:
            continue
        mood, ar, mb = get_mood(i)
        if "退潮" in mood:
            continue

        cand = []
        for code, r in zt[prv].items():
            name = r["name"]
            if "ST" in name or code.startswith(("4", "8", "9")):
                continue
            mv = r["float_mv"] / 1e8 if r["float_mv"] else 0
            if mv < 20:
                continue
            if (tdy, code) not in auction:
                continue

            buy_p, gap, auc_amt = auction[(tdy, code)]
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
            gx10 = gx(code, tdy, 10)

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

            if gx10 >= 5:
                score += 1.0
            elif gx10 >= 3:
                score += 0.5
            if "分歧" in mood:
                score -= 1.5

            if score >= 14:
                cand.append({"code": code, "name": name, "score": score, "gap": gap,
                             "lt": lt, "buy_p": buy_p, "vr": vr, "mv": mv, "e": e, "gx10": gx10})

        cand.sort(key=lambda x: x["score"], reverse=True)
        for c in cand[:3]:
            ret = None
            if i + 1 < len(days):
                nxt = days[i + 1]
                no = auction.get((nxt, c["code"]))
                nc = closes.get((nxt, c["code"]))
                sl = [x for x in [no[0] if no else 0, nc if nc else 0] if x > 0]
                if sl:
                    ret = (max(sl) / c["buy_p"] - 1) * 100
            trades.append({
                "date": tdy, "code": c["code"], "name": c["name"],
                "s": round(c["score"], 1), "gap": c["gap"], "lt": c["lt"],
                "vr": round(c["vr"], 3), "mv": c["mv"], "e": c["e"],
                "gx": c["gx10"], "ret": ret, "mood": mood,
            })

    if not trades:
        print("\n⚠️ 回测区间内无符合条件交易（免费源竞价数据仅近5日，窗口可能太短）")
        return

    dv = [t for t in trades if t["ret"] is not None]
    if not dv:
        print(f"\n⚠️ 共 {len(trades)} 笔信号，但次日数据缺失无法统计收益")
        return

    rets = [t["ret"] for t in dv]
    t = len(dv)
    w = sum(1 for r in rets if r > 0)
    aw = sum(r for r in rets if r > 0) / w if w else 0
    al = sum(r for r in rets if r <= 0) / (t - w) if (t - w) else 0

    print(f"\n🏆 v5免费源版: {t}笔, 胜率{w/t*100:.1f}%, 均收{sum(rets)/t:+.2f}%, 累计{sum(rets):+.2f}%")
    if al:
        print(f"   盈亏比{abs(aw/al):.2f}, 最大赚{max(rets):+.2f}%, 最大亏{min(rets):+.2f}%")

    print("\n【每日】")
    from collections import defaultdict
    by_date = defaultdict(list)
    for x in dv:
        by_date[x["date"]].append(x["ret"])
    for dt in sorted(by_date):
        rr = by_date[dt]
        print(f"  {dt}:{len(rr)}笔,胜{sum(1 for v in rr if v>0)}笔"
              f"({sum(1 for v in rr if v>0)/len(rr)*100:.0f}%),均{sum(rr)/len(rr):+.1f}%,总{sum(rr):+.1f}%")

    print("\n【分数段】")
    for lo, hi in [(14, 16.5), (16.5, 18), (18, 20), (20, 25)]:
        sub = [x["ret"] for x in dv if lo <= x["s"] < hi]
        if sub:
            print(f"  {lo:.0f}~{hi:.0f}分:{len(sub)}笔,"
                  f"胜率{sum(1 for v in sub if v>0)/len(sub)*100:.0f}%,均收{sum(sub)/len(sub):+.2f}%")

    print("\n【TOP3详情】")
    for x in dv:
        gs = f"股{x['gx']}次" if x["gx"] > 0 else ""
        rs = f"✅ +{x['ret']:.1f}%" if x["ret"] > 0 else f"❌ {x['ret']:.1f}%"
        print(f"  {x['date']} {x['name']:>6s}: {x['s']:.1f}分 {x['lt']}板 {x['gap']:+.0f}% {gs} → {rs}")


if __name__ == "__main__":
    main()
