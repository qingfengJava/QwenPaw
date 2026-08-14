# -*- coding: utf-8 -*-
"""Debug: run department_tree standalone to surface the /directory/departments 500."""
import asyncio
import os

env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
if os.path.exists(env_path):
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("QWENPAW_PG_DSN="):
            os.environ["QWENPAW_PG_DSN"] = line.split("=", 1)[1].strip().strip('"')

from qwenpaw.db.migrate import run_migrations  # noqa: E402
import qwenpaw.app.enterprise as enterprise_mod  # noqa: E402
from qwenpaw.app.orgs.service import (  # noqa: E402
    get_org_service,
)


async def main() -> None:
    await run_migrations()
    # Standalone script: mark the schema ready like the app lifespan does.
    enterprise_mod._schema_ready = True  # pylint: disable=protected-access
    tree = await get_org_service().department_tree()
    print("tree nodes:", len(tree))
    for node in tree:
        print("root:", node.id, node.name, "children:", len(node.children))
        print("dump ok:", bool(node.model_dump()))


asyncio.run(main())
