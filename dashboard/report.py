"""
手机版报告生成
读取 output/daily_summary.json，渲染移动优先的纯静态 HTML（无外部依赖）。
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional


def load_summary(path: str) -> Dict:
    if not os.path.exists(path):
        return {"error": "报告不存在"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_mobile_html(summary: Dict, out_path: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    data_date = summary.get("data_date", "-")
    picks = summary.get("picks", [])
    bt = summary.get("backtest", {})
    pb = summary.get("pool_bench", {})
    factors = summary.get("factors", [])[:12]
    weights = summary.get("weights", {})

    pick_rows = ""
    for p in picks:
        pct = p.get("pct")
        pct_txt = f"{pct:+.2f}%" if pct is not None else "-"
        pct_cls = "up" if (pct or 0) >= 0 else "down"
        pick_rows += (
            f"<tr><td class='rk'>{p['rank']}</td>"
            f"<td class='nm'>{p.get('name','-')}<span class='cd'>{p.get('code','')}</span></td>"
            f"<td class='sc'>{p.get('score', 0):.2f}</td>"
            f"<td class='px'>{p.get('close','-') if p.get('close') else '-'}</td>"
            f"<td class='{pct_cls}'>{pct_txt}</td></tr>"
        )
    if not pick_rows:
        pick_rows = "<tr><td colspan='5' class='empty'>暂无选股结果</td></tr>"

    def card(label, value, sub=""):
        sub_html = f"<div class='cs'>{sub}</div>" if sub else ""
        return (f"<div class='card'><div class='cv'>{value}</div>"
                f"<div class='cl'>{label}</div>{sub_html}</div>")

    fac_rows = ""
    for f in factors:
        sig = "sig" if f.get("significant") else ""
        fac_rows += (f"<tr class='{sig}'><td>{f.get('name','')}</td>"
                     f"<td>{f.get('ic',0):+.3f}</td><td>{f.get('t',0):+.1f}</td>"
                     f"<td>{f.get('win',0):.0f}%</td></tr>")
    if not fac_rows:
        fac_rows = "<tr><td colspan='4' class='empty'>暂无因子数据</td></tr>"

    weekly = summary.get("weekly", [])
    wk_rows = ""
    for w in weekly:
        ex300 = f"{w['excess300']:+.2f}%" if w.get("excess300") is not None else "-"
        ex500 = f"{w['excess500']:+.2f}%" if w.get("excess500") is not None else "-"
        wk_rows += (f"<tr><td>{w['pick_date']}</td><td>{w['n']}只</td>"
                    f"<td>{w['avg_return']:+.2f}%</td><td>{w['win_rate']:.0f}%</td>"
                    f"<td>{ex300}</td><td>{ex500}</td></tr>")
    wk_panel = ""
    if wk_rows:
        wk_panel = f"""
<div class="panel">
  <div class="pt">选股跟踪（到期批次实际表现）</div>
  <table>
    <tr><th>选股日</th><th>数量</th><th>平均收益</th><th>上涨比</th><th>vs沪深300</th><th>vs中证500</th></tr>
    {wk_rows}
  </table>
</div>"""

    w_rows = "".join(
        f"<span class='chip'>{k} {v * 100:.0f}%</span>" for k, v in weights.items())

    err = ""
    if summary.get("error"):
        err = f"<div class='err'>⚠ {summary['error']}</div>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>量化选股 · 手机版</title>
<style>
:root {{ --bg:#f4f6fa; --card:#fff; --ink:#1b2430; --sub:#6b7686; --up:#e0443d; --down:#0a8f5c; --acc:#2f6fed; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--ink); font:14px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; padding:14px 12px 40px; }}
h1 {{ font-size:18px; margin:4px 0 2px; }}
.meta {{ color:var(--sub); font-size:12px; margin-bottom:12px; }}
.err {{ background:#fdeceb; color:#b3261e; padding:10px 12px; border-radius:10px; margin-bottom:12px; }}
.panel {{ background:var(--card); border-radius:14px; padding:12px; margin-bottom:14px; box-shadow:0 1px 4px rgba(20,30,60,.06); }}
.pt {{ font-size:13px; font-weight:600; margin-bottom:8px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ font-size:11px; color:var(--sub); font-weight:500; text-align:left; padding:4px 2px; border-bottom:1px solid #eef1f6; }}
td {{ padding:7px 2px; border-bottom:1px solid #f2f4f8; font-size:13px; }}
tr:last-child td {{ border-bottom:none; }}
.rk {{ color:var(--sub); width:22px; }}
.nm {{ font-weight:600; }}
.cd {{ display:block; color:var(--sub); font-size:11px; font-weight:400; }}
.sc {{ color:var(--acc); }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }}
.empty {{ color:var(--sub); text-align:center; padding:16px 0; }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
.card {{ background:#f8fafc; border-radius:10px; padding:8px 6px; text-align:center; }}
.cv {{ font-size:15px; font-weight:700; }}
.cl {{ font-size:11px; color:var(--sub); margin-top:2px; }}
.cs {{ font-size:10px; color:var(--sub); }}
.sig td {{ background:#f0f6ff; }}
.chip {{ display:inline-block; background:#eef3ff; color:var(--acc); border-radius:20px; padding:3px 10px; margin:3px 4px 0 0; font-size:12px; }}
.foot {{ color:var(--sub); font-size:11px; text-align:center; margin-top:16px; }}
</style>
</head>
<body>
<h1>📈 量化选股 · 手机版</h1>
<div class="meta">生成于 {now} ｜ 数据截至 {data_date}</div>
{err}
<div class="panel">
  <div class="pt">今日选股 Top {len(picks)}（质量过滤 + 因子得分）</div>
  <table>
    <tr><th>#</th><th>股票</th><th>得分</th><th>收盘</th><th>涨跌</th></tr>
    {pick_rows}
  </table>
</div>
<div class="panel">
  <div class="pt">回测参考（2018 至今，月度调仓）</div>
  <div class="grid">
    {card("年化", f"{bt.get('annual_return','-')}%")}
    {card("夏普", f"{bt.get('sharpe','-')}")}
    {card("最大回撤", f"{bt.get('max_drawdown','-')}%")}
    {card("月胜率", f"{bt.get('monthly_win_rate','-')}%")}
    {card("vs沪深300", f"{bt.get('excess_return','-')}%")}
    {card("vs池基准", f"{pb.get('excess_return','-')}%", f"IR {pb.get('info_ratio','-')}")}
  </div>
</div>
{wk_panel}
<div class="panel">
  <div class="pt">因子有效性 Top 12（IC / t 值）</div>
  <table>
    <tr><th>因子</th><th>IC</th><th>t值</th><th>胜率</th></tr>
    {fac_rows}
  </table>
</div>
<div class="panel">
  <div class="pt">最近一期因子权重</div>
  {w_rows if w_rows else '<span class="empty">暂无</span>'}
</div>
<div class="foot">本系统为量化研究工具，所有输出不构成投资建议；股市有风险，入市需谨慎。</div>
</body>
</html>"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html
