# -*- coding: utf-8 -*-
"""Alembic environment (online-only, programmatic configuration).

QwenPaw runs migrations programmatically via ``qwenpaw.db.migrate`` so a
private deployment never needs an ``alembic.ini`` file. The engine (or its
URL) is handed over through ``config.attributes``.
"""
from __future__ import annotations

from alembic import context

from qwenpaw.db.base import Base
from qwenpaw.db import models  # noqa: F401  (register tables on metadata)
from qwenpaw.db import models_enterprise  # noqa: F401  (enterprise tables)
from qwenpaw.db import models_agent_docs  # noqa: F401  (agent documents)
from qwenpaw.db import models_crons  # noqa: F401  (cron job plane)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """Run migrations against the connection passed by the caller."""
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "qwenpaw.db alembic env requires a connection via "
            "config.attributes['connection']",
        )
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
