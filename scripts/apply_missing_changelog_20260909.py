# -*- coding: utf-8 -*-
"""按序执行 db/feature/agent_run_logs_20260908/changelog/20260909/ 下缺失的 6 个 SQL 变更。

执行前打印每条语句；全部幂等（IF NOT EXISTS / IF EXISTS），可重复执行。
"""
import asyncio
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import asyncpg

DSN = "postgresql://qwenpaw:qwenpaw_test@127.0.0.1:5432/qwenpaw"

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_DIR = (
    ROOT / "db" / "feature" / "agent_run_logs_20260908"
    / "changelog" / "20260909"
)


def split_statements(sql_text: str) -> list:
    """剔除 -- 注释行后按 ; 切分语句，去掉空白块。"""
    lines = []
    for line in sql_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("--"):
            continue
        # 去掉行尾注释（语句内无字符串含 -- 的场景，本批 SQL 均安全）
        if "--" in line:
            line = line.split("--")[0].rstrip()
        if line.strip():
            lines.append(line)
    joined = "\n".join(lines)
    return [s.strip() for s in joined.split(";") if s.strip()]


async def main():
    files = sorted(CHANGELOG_DIR.glob("*.sql"))
    print(f"待执行 changelog 文件 {len(files)} 个：")
    for f in files:
        print(" -", f.name)

    conn = await asyncpg.connect(DSN)
    try:
        for f in files:
            stmts = split_statements(f.read_text(encoding="utf-8"))
            print(f"\n>>> {f.name}（{len(stmts)} 条语句）")
            for i, stmt in enumerate(stmts, 1):
                preview = " ".join(stmt.split())[:90]
                await conn.execute(stmt)
                print(f"    [{i}/{len(stmts)}] OK  {preview}")
    finally:
        await conn.close()

    print("\n=== 全部执行完成 ===")


asyncio.run(main())
