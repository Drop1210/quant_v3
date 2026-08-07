"""多进程增量下载路径测试（必须从真实脚本运行）"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from data.data_engine import DataEngine


def main() -> None:
    eng = DataEngine()
    df = eng._fetch_many(["600519", "000001", "300750", "000858", "601318"],
                         "20260728", "20260807")
    print("返回行数:", len(df))
    if len(df) > 0:
        print(df.groupby("code").size().to_string())
        print(df[["code", "date", "close"]].tail(5).to_string(index=False))
    print("多进程路径:", "PASS" if len(df) >= 40 else "FAIL")


if __name__ == "__main__":
    main()
