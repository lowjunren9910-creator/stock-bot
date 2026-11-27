"""网站直接改 GitHub 上的设定档（自选股 watchlist.yml、新闻追踪 follow.json、我的仪表板 my_dashboard.json）。

需要在 Streamlit 的 Secrets 加：
  GITHUB_TOKEN = "github_pat_..."   （Fine-grained token，只给这个 repo 的 Contents: Read and write）
  GITHUB_REPO  = "你的帐号/stock-bot"
没有设定的话：网站照样能用，只是改设定要自己去 GitHub 改（会给你复制用的内容）。
"""
from __future__ import annotations

import base64
import os
import re

import requests

API = "https://api.github.com"


def _cfg() -> tuple[str | None, str | None]:
    tok, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO")
    try:
        import streamlit as st
        tok = tok or st.secrets.get("GITHUB_TOKEN")
        repo = repo or st.secrets.get("GITHUB_REPO")
    except Exception:
        pass
    return tok, repo


def ready() -> bool:
    tok, repo = _cfg()
    return bool(tok and repo)


def _h() -> dict:
    return {"Authorization": f"Bearer {_cfg()[0]}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def get(path: str) -> tuple[str | None, str | None]:
    """回传 (内容, sha)；文件不存在 → (None, None)。"""
    tok, repo = _cfg()
    r = requests.get(f"{API}/repos/{repo}/contents/{path}", headers=_h(), timeout=20)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    d = r.json()
    return base64.b64decode(d["content"]).decode("utf-8"), d["sha"]


def put(path: str, text: str, message: str, sha: str | None = None) -> str:
    tok, repo = _cfg()
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(f"{API}/repos/{repo}/contents/{path}", headers=_h(), json=body, timeout=30)
    if r.status_code == 409:          # 刚好被自动任务改了：重新读一次再写
        _, sha2 = get(path)
        body["sha"] = sha2
        r = requests.put(f"{API}/repos/{repo}/contents/{path}", headers=_h(), json=body, timeout=30)
    if r.status_code in (401, 403):
        raise PermissionError("GitHub token 没有权限（要给这个 repo 的 Contents: Read and write）")
    r.raise_for_status()
    return r.json().get("commit", {}).get("html_url", "")


def update(path: str, fn, message: str, local: str | None = None) -> tuple[str, str]:
    """读 GitHub 上最新的内容 → fn(旧内容) 得到新内容 → 写回。回传 (新内容, commit 网址)。"""
    old, sha = get(path)
    if old is None and local:
        try:
            old = open(local, encoding="utf-8").read()
        except Exception:
            old = None
    new = fn(old)
    url = put(path, new, message, sha)
    if local:                                   # 网站这边也马上用新版本（不用等重新部署）
        try:
            with open(local, "w", encoding="utf-8") as f:
                f.write(new)
        except Exception:
            pass
    return new, url


# ---------------------------------------------------------------------------
# watchlist.yml：只改 stocks 部分，上面的说明注释保留
# ---------------------------------------------------------------------------

def _split_watchlist(text: str) -> tuple[str, dict]:
    import yaml
    m = re.search(r"^stocks\s*:", text or "", re.M)
    head = (text or "")[:m.start()] if m else (text or "")
    data = yaml.safe_load(text or "") or {}
    return head, data


def _dump_watchlist(head: str, data: dict) -> str:
    import yaml
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, indent=2)
    body = re.sub(r"\n(- )", r"\n\n\1", body)                 # 每只股票之间空一行，比较好读
    return head.rstrip() + "\n\n" + body


def edit_watchlist(text: str, action: str, ticker: str, note: str | None = None,
                   alerts: dict | None = None) -> tuple[str, str]:
    """action：add / remove / alert / clear_alerts。回传 (新内容, 说明)。"""
    import analysis as A
    head, data = _split_watchlist(text)
    stocks = data.setdefault("stocks", []) or []
    data["stocks"] = stocks
    want = A.normalize_ticker(ticker)

    def same(s):
        t = s.get("ticker") if isinstance(s, dict) else s
        try:
            return A.normalize_ticker(str(t)) == want
        except Exception:
            return str(t).upper() == ticker.upper()

    idx = next((i for i, s in enumerate(stocks) if same(s)), None)
    if action == "remove":
        if idx is None:
            return text, f"{ticker} 本来就不在自选股"
        stocks.pop(idx)
        return _dump_watchlist(head, data), f"从自选股拿掉 {ticker}"
    if idx is None:
        stocks.append({"ticker": ticker.upper()})
        idx = len(stocks) - 1
        msg = f"把 {ticker} 加进自选股"
    else:
        msg = f"更新 {ticker}"
    s = stocks[idx] if isinstance(stocks[idx], dict) else {"ticker": stocks[idx]}
    stocks[idx] = s
    if note:
        s["note"] = note
    if action == "clear_alerts":
        s.pop("alerts", None)
        msg = f"取消 {ticker} 的全部提醒"
    elif alerts:
        ok = {k: float(v) for k, v in alerts.items()
              if k in ("below", "above", "change_pct", "rsi_below", "rsi_above") and v not in (None, "")}
        if ok:
            s.setdefault("alerts", {}).update(ok)
            msg += "：提醒 " + "、".join(f"{ALERT_ZH[k]} {v:g}" for k, v in ok.items())
    return _dump_watchlist(head, data), msg


ALERT_ZH = {"below": "跌破", "above": "升破", "change_pct": "单日涨跌超过 ±%", "rsi_below": "RSI 低于",
            "rsi_above": "RSI 高于"}
