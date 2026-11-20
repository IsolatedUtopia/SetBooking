#!/usr/bin/env python
"""Django 的命令行入口，所有 manage.py 命令都从这里进来。"""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backoffice.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "无法导入 Django：请确认已激活 .venv 并安装了 django。"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()