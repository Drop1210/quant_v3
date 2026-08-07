"""
早间晨报：重新推送昨日选股结果（不重算，秒级完成）
由 .github/workflows/morning.yml 在 07:30 触发。
"""

import json
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from dashboard import push


def main() -> None:
    path = os.path.join(PROJECT_ROOT, "output", "daily_summary.json")
    if not os.path.exists(path):
        push.push_text("早间晨报",
                       "系统还没有生成过选股报告，请先在 Actions 里手动运行一次 daily-quant")
        return
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    lines = [f"☀️ 早间晨报 {datetime.now():%m-%d}（数据截至 {s.get('data_date','-')}）"]
    for p in s.get("picks", [])[:10]:
        pct = p.get("pct")
        pct_txt = f" {pct:+.2f}%" if pct is not None else ""
        pe = p.get("pe")
        pe_txt = f" PE{pe}" if pe else ""
        lines.append(f"· {p.get('name','')}({p.get('code','')}) "
                     f"得分{p.get('score',0):.2f}{pct_txt}{pe_txt}")
    sp = s.get("small_picks", [])
    if sp:
        lines.append("")
        lines.append(f"跟单建议 Top {len(sp)}：")
        for p in sp:
            pe = p.get("pe")
            pe_txt = f" PE{pe}" if pe else ""
            hand = f"每手{p.get('close',0)*100:.0f}元" if p.get("close") else ""
            lines.append(f"· {p.get('name','')}({p.get('code','')}) "
                         f"收盘{p.get('close','-')}{pe_txt} {p.get('industry','')} {hand}")
    lines.append("")
    lines.append("昨日选股结果，仅供参考，不构成投资建议")
    push.push_text("早间晨报", "\n".join(lines))


if __name__ == "__main__":
    main()
