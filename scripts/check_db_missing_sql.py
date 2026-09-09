# -*- coding: utf-8 -*-
"""探查当前 PG 库状态：与 db/feature/agent_run_logs_20260908/changelog 对比，找出缺失对象"""
import asyncio
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import asyncpg

DSN = "postgresql://qwenpaw:qwenpaw_test@127.0.0.1:5432/qwenpaw"


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        # 1. 所有业务表
        tables = await conn.fetch(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        table_names = [r["tablename"] for r in tables]
        print("=== 当前库中所有表 (%d) ===" % len(table_names))
        for t in table_names:
            print(" -", t)

        # 2. changelog 需要的表
        expected_tables = [
            "agent_documents", "audit_events", "agent_runs",
            "agent_run_spans", "provider_configs", "model_active_slots",
            "provider_models",
        ]
        print("\n=== changelog 期望表核对 ===")
        missing_tables = []
        for t in expected_tables:
            ok = t in table_names
            print((" [OK] " if ok else " [MISSING] ") + t)
            if not ok:
                missing_tables.append(t)

        # 3. chats / session_states 的 agent_id 列与索引
        print("\n=== chats / session_states 列核对 ===")
        cols = await conn.fetch(
            """
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('chats', 'session_states')
              AND column_name = 'agent_id'
            """
        )
        got = {(r["table_name"], r["column_name"]) for r in cols}
        for tb in ("chats", "session_states"):
            ok = (tb, "agent_id") in got
            print((" [OK] " if ok else " [MISSING] ") + tb + ".agent_id")

        print("\n=== 相关索引核对 ===")
        idx = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname IN ('ix_chats_tenant_agent',
                                'ix_agent_runs_agent_started',
                                'ix_agent_run_spans_run',
                                'idx_agent_documents_agent',
                                'idx_audit_events_ts',
                                'idx_audit_events_workspace',
                                'idx_audit_events_agent',
                                'idx_audit_events_tool')
            """
        )
        idx_names = {r["indexname"] for r in idx}
        for name in ("ix_chats_tenant_agent", "ix_agent_runs_agent_started",
                     "ix_agent_run_spans_run", "idx_agent_documents_agent",
                     "idx_audit_events_ts", "idx_audit_events_workspace",
                     "idx_audit_events_agent", "idx_audit_events_tool"):
            print((" [OK] " if name in idx_names else " [MISSING] ") + name)

        # 4. session_states 主键核对（应含 agent_id）
        print("\n=== session_states 主键核对 ===")
        pk_cols = await conn.fetch(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                 AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'session_states'::regclass
              AND i.indisprimary
            ORDER BY a.attnum
            """
        )
        pk_names = [r["attname"] for r in pk_cols]
        print(" 主键列:", pk_names)
        if "agent_id" not in pk_names:
            print(" [MISSING] 主键未包含 agent_id")

        # 5. 备注覆盖抽查（20260908 的 COMMENT 变更是否已应用）
        print("\n=== 备注(COMMENT)覆盖抽查 ===")
        commented = await conn.fetchval(
            """
            SELECT count(*) FROM pg_tables t
            WHERE t.schemaname='public'
              AND obj_description(('"' || t.tablename || '"')::regclass) IS NOT NULL
            """
        )
        total = len(table_names)
        print(f" 表级备注: {commented}/{total}")

        # 6. provider_configs 关键列
        print("\n=== provider_configs 列核对 ===")
        pcols = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='provider_configs'
            ORDER BY ordinal_position
            """
        )
        print(" ", [r["column_name"] for r in pcols])

        print("\n=== 缺失汇总 ===")
        print("missing_tables =", missing_tables)
    finally:
        await conn.close()


asyncio.run(main())
