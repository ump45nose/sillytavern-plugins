#!/usr/bin/env python3
"""通过本机已获授权的 Python 启动同步器，保留后台任务的 TCC 责任主体。"""

import subprocess
import sys


def main():
    """签名 main() -> int：仅转交显式 Node/脚本参数并返回真实退出码。"""
    if len(sys.argv) < 3:
        print("缺少 Node 或同步脚本路径", file=sys.stderr)
        return 2
    # 不读取业务数据、不修改权限；由既有授权进程运行同一范围的同步任务。
    return subprocess.run(sys.argv[1:], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
