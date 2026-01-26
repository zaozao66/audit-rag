#!/usr/bin/env python3
"""
RAG系统主入口
"""

import sys
import os

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from cli_app import main as cli_main


def main():
    cli_main()


if __name__ == "__main__":
    main()