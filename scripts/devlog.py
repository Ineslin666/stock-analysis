#!/usr/bin/env python3
"""开发日志助手（见 文档/07-开发日志规范.md）

用法：python3 scripts/devlog.py
- 若 开发日志/今天.md 已存在：不做任何修改，打印已存在
- 否则：创建今日日志文件，按模板初始化，
  并自动继承最近一份日志中未完成的待办事项
仅使用标准库，系统 python3 即可运行。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "开发日志"

TEMPLATE = """# 开发日志 {today}

## 今日完成
（今天开始工作后由 Claude 自动填写）

## 待办事项
{todos}

## 明日计划
- [ ] （会话结束时由 Claude 填写）

## 备注 / 问题
无
"""


def find_latest_log() -> Path | None:
    """返回日期最近的一份日志文件，没有则返回 None。"""
    logs = sorted(
        (p for p in LOGDIR.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name)),
        reverse=True,
    )
    return logs[0] if logs else None


def collect_pending_todos(text: str) -> list[str]:
    """提取日志中「待办事项」「明日计划」两个区块里未勾选的条目（含其下缩进续行）。"""
    items: list[str] = []
    in_section = False
    buffer: list[str] = []

    def flush():
        if buffer:
            items.append("\n".join(buffer))
            buffer.clear()

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            in_section = line in ("## 待办事项", "## 明日计划")
            continue
        if in_section:
            if line.startswith("- [ ]"):
                flush()
                buffer.append(line)
            elif line.startswith("- [x]"):
                flush()
            elif buffer and (line.startswith("  ") or line.strip() == ""):
                buffer.append(line)
            else:
                flush()
    flush()
    return items


def main() -> int:
    today = date.today().isoformat()
    today_file = LOGDIR / f"{today}.md"

    if today_file.exists():
        print(f"今日日志已存在：{today_file}")
        return 0

    todos: list[str] = []
    latest = find_latest_log()
    if latest is not None:
        pending = collect_pending_todos(latest.read_text(encoding="utf-8"))
        todos = pending or ["（无继承待办）"]
        print(f"继承来源：{latest.name}（{len(pending)} 条未完成待办）")
    else:
        todos = ["（无继承待办）"]

    LOGDIR.mkdir(parents=True, exist_ok=True)
    todo_block = "\n".join(todos)
    today_file.write_text(TEMPLATE.format(today=today, todos=todo_block), encoding="utf-8")
    print(f"已创建今日日志：{today_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
