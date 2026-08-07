"""运行失败通知（走所有已配置的推送通道）"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dashboard import push


def main() -> None:
    push.push_text("量化系统运行失败",
                   "今日量化运行失败，请到 GitHub Actions 查看日志排查。")


if __name__ == "__main__":
    main()
