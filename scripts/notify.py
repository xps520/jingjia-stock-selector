#!/usr/bin/env python3
"""notify.py — 微信推送（Server酱），供竞价选股脚本调用。

配置：环境变量 SERVERCHAN_SENDKEY（不写死在代码里）。
  export SERVERCHAN_SENDKEY=SCTxxxxxxxx
  或在 GitHub Actions 里配置同名 Secret。

用法：
  from notify import send
  send("标题", "正文")
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request

SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
_TIMEOUT = 15


def send(title: str, content: str = "") -> bool:
    """发送微信推送。失败只打印，不抛异常（不阻断选股主流程）。"""
    if not SERVERCHAN_SENDKEY:
        print("[推送] 未配置 SERVERCHAN_SENDKEY，跳过推送")
        return False
    qs = urllib.parse.urlencode({"title": title, "desp": content})
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send?{qs}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
        print(f"[推送] 已发送: {title}")
        return True
    except Exception as e:          # noqa: BLE001
        print(f"[推送] 失败({type(e).__name__}): {e}")
        return False


def send_report(title: str, report_md: str) -> bool:
    """发送 Markdown 报告（Server酱 desp 支持 Markdown）。"""
    return send(title, report_md)
