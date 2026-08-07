"""
手机推送：企业微信机器人 / Server酱 / PushPlus / Bark

钥匙优先级：环境变量 > push_settings.json > config.py
GitHub Actions 中用仓库 Secrets 注入环境变量，本地开发用 push_settings.json。
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import cfg

SETTINGS_PATH = os.path.join(PROJECT_ROOT, "push_settings.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "output", "push_log.txt")

ENV_MAP = {
    "wechat_webhook": "WECHAT_WEBHOOK",
    "serverchan_key": "SERVERCHAN_KEY",
    "pushplus_token": "PUSHPLUS_TOKEN",
    "bark_key": "BARK_KEY",
    "web_token": "WEB_TOKEN",
}


def load_settings() -> Dict[str, str]:
    s = {
        "wechat_webhook": cfg.push.wechat_webhook or "",
        "serverchan_key": cfg.push.serverchan_key or "",
        "pushplus_token": cfg.push.pushplus_token or "",
        "bark_key": cfg.push.bark_key or "",
        "web_token": cfg.push.web_token or "",
    }
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                s.update({k: v for k, v in json.load(f).items() if isinstance(v, str)})
        except Exception:
            pass
    for k, env in ENV_MAP.items():
        v = os.environ.get(env, "")
        if v:
            s[k] = v
    return s


def save_settings(updates: Dict[str, str]) -> Dict[str, str]:
    s = load_settings()
    for k in ENV_MAP:
        if k in updates:
            s[k] = (updates[k] or "").strip()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    return s


def configured_channels(settings: Optional[Dict[str, str]] = None) -> List[str]:
    s = settings or load_settings()
    ch = []
    if s.get("wechat_webhook", "").startswith("https://qyapi.weixin.qq.com"):
        ch.append("wechat")
    if s.get("serverchan_key"):
        ch.append("serverchan")
    if s.get("pushplus_token"):
        ch.append("pushplus")
    if s.get("bark_key"):
        ch.append("bark")
    return ch


def _log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _fit_bytes(s: str, limit: int) -> str:
    if len(s.encode("utf-8")) <= limit:
        return s
    out, n = "", 0
    for ch in s:
        n += len(ch.encode("utf-8"))
        if n > limit - 3:
            break
        out += ch
    return out + "..."


def _post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def send_wechat(webhook: str, text: str) -> None:
    text = _fit_bytes(text, 1800)
    r = _post_json(webhook, {"msgtype": "text", "text": {"content": text}})
    if r.get("errcode", -1) != 0:
        raise RuntimeError(f"企业微信返回: {r}")


def send_serverchan(key: str, title: str, text: str) -> None:
    url = (f"https://sctapi.ftqq.com/{urllib.parse.quote(key)}.send"
           f"?title={urllib.parse.quote(title)}&desp={urllib.parse.quote(text)}")
    raw = _get(url)
    try:
        j = json.loads(raw)
    except Exception:
        j = {}
    if j.get("code") not in (0, "0", 200):
        raise RuntimeError(f"Server酱返回: {raw[:200]}")


def send_pushplus(token: str, title: str, text: str) -> None:
    r = _post_json("https://www.pushplus.plus/send",
                   {"token": token, "title": title, "content": text,
                    "template": "txt"})
    if r.get("code") != 200:
        raise RuntimeError(f"PushPlus返回: {r}")


def send_bark(key: str, title: str, text: str) -> None:
    text = _fit_bytes(text, 700)
    url = (f"https://api.day.app/{key}/{urllib.parse.quote(title)}/"
           f"{urllib.parse.quote(text)}?sound=alarm")
    _get(url)


def push_text(title: str, text: str, channels: Optional[List[str]] = None) -> List[str]:
    settings = load_settings()
    chs = channels or configured_channels(settings)
    if not chs:
        _log("未配置任何推送通道（企业微信/Server酱/PushPlus/Bark 任选其一）")
        return []
    ok = []
    for ch in chs:
        try:
            if ch == "wechat":
                send_wechat(settings["wechat_webhook"], f"{title}\n{text}")
            elif ch == "serverchan":
                send_serverchan(settings["serverchan_key"], title, text)
            elif ch == "pushplus":
                send_pushplus(settings["pushplus_token"], title, text)
            elif ch == "bark":
                send_bark(settings["bark_key"], title, text)
            else:
                continue
            ok.append(ch)
            _log(f"[OK] {ch} 推送成功")
        except Exception as e:
            _log(f"[FAIL] {ch} 推送失败: {e}")
    return ok


def build_text(summary: Dict) -> str:
    lines = []
    picks = summary.get("picks", [])
    if picks:
        lines.append(f"今日选股 Top {len(picks)}：")
        for p in picks[:10]:
            pct = p.get("pct")
            pct_txt = f" {pct:+.2f}%" if pct is not None else ""
            pe = p.get("pe")
            pe_txt = f" PE{pe}" if pe else ""
            lines.append(f"· {p.get('name','')}({p.get('code','')}) "
                         f"得分{p.get('score',0):.2f}{pct_txt}{pe_txt}")
    sp = summary.get("small_picks", [])
    if sp:
        lines.append("")
        lines.append(f"小资金 Top {len(sp)}（每手约{sp[0].get('close',0)*100:.0f}元起）：")
        for p in sp:
            pe = p.get("pe")
            pe_txt = f" PE{pe}" if pe else ""
            lines.append(f"· {p.get('name','')}({p.get('code','')}) "
                         f"收盘{p.get('close','-')}{pe_txt} {p.get('industry','')}")
    bt = summary.get("backtest", {})
    if bt:
        lines.append("")
        lines.append(f"回测参考：年化{bt.get('annual_return','-')}% "
                     f"夏普{bt.get('sharpe','-')} 回撤{bt.get('max_drawdown','-')}% "
                     f"月胜率{bt.get('monthly_win_rate','-')}%")
        pb = summary.get("pool_bench", {})
        if pb.get("excess_return") is not None:
            lines.append(f"vs沪深300 {bt.get('excess_return','-')}% | "
                         f"vs池基准 {pb.get('excess_return','-')}%")
    if summary.get("error"):
        lines.append("")
        lines.append(f"⚠ {summary['error']}")
    lines.append("")
    lines.append("仅供参考，不构成投资建议")
    return "\n".join(lines)
