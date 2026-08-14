# -*- coding: utf-8 -*-
"""Smoke: mount the xian router standalone and probe the new endpoints."""
import os

# Pick up the local dev DSN (same as integration tests would).
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("QWENPAW_PG_DSN="):
            os.environ["QWENPAW_PG_DSN"] = line.split("=", 1)[1].strip().strip('"')

from fastapi import FastAPI
from fastapi.testclient import TestClient  # noqa: E402

from qwenpaw.app.routers.xian import router as xian_router  # noqa: E402

app = FastAPI()
app.include_router(xian_router, prefix="/api")
client = TestClient(app)

for path in [
    "/api/xian/directory/users",
    "/api/xian/directory/departments",
    "/api/xian/resources/skills",
    "/api/xian/resources/connectors",
    "/api/xian/projects",
]:
    res = client.get(path)
    body = res.text[:100].replace("\n", " ")
    print(f"{path} -> {res.status_code} {body}")
