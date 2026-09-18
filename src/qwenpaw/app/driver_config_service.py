# -*- coding: utf-8 -*-
"""Application service for persisted Driver configuration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..drivers.capabilities import DriverRuntimeInfo
from ..drivers.contracts import DriverCard, coerce_card
from ..drivers.credentials.store import (
    AsyncCredentialStore,
)
from ..drivers.credentials.types import CredentialRecord
from ..drivers.errors import CredentialNotFoundError, DriverCardError
from ..drivers.storage import (
    AsyncDriverCardStore,
    card_path,
)
from .driver_config.pg_store import get_driver_pg_store

logger = logging.getLogger(__name__)
_MANAGER_NOT_READY_DETAIL = (
    "Driver manager is not ready yet, please try again later"
)


class DriverConfigService:
    """Own app-layer DriverCard and credential persistence concerns."""

    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace
        self._reload_tasks: set[asyncio.Task] = set()

    @property
    def cards_dir(self) -> Path:
        return self._workspace.workspace_dir / "drivers"

    @property
    def credential_store(self) -> AsyncCredentialStore:
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is not None and hasattr(manager, "credential_store"):
            return manager.credential_store
        return AsyncCredentialStore(
            self._workspace.workspace_dir / "credentials.yaml",
        )

    @property
    def card_store(self) -> AsyncDriverCardStore:
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is not None and hasattr(manager, "card_store"):
            return manager.card_store
        return AsyncDriverCardStore(self.cards_dir)

    def card_path(self, name: str, *, protocol: str) -> Path:
        try:
            return card_path(self.cards_dir, name, protocol=protocol)
        except DriverCardError as exc:
            raise HTTPException(400, detail=str(exc)) from exc

    # -- PG 权威平面适配（T12：写穿 PG + 文件投影，读优先 PG 回退文件）------

    def _agent_id(self) -> str:
        """解析归属员工 id（缺省时回落 workspace 目录名）。"""
        agent_id = str(getattr(self._workspace, "agent_id", "") or "").strip()
        if agent_id:
            return agent_id
        return Path(self._workspace.workspace_dir).name

    @staticmethod
    def _card_to_payload(card: DriverCard) -> dict:
        """把 DriverCard 拆成 PG 列（enabled/spec/policy）与自然键。"""
        spec = {
            "endpoint": card.endpoint,
            "config": card.config,
            "credentials": {
                alias: asdict(ref) for alias, ref in card.credentials.items()
            },
        }
        return {
            "name": card.name,
            "protocol": card.protocol,
            "enabled": card.enabled,
            "spec": spec,
            "policy": asdict(card.policy),
        }

    @staticmethod
    def _payload_to_card(payload: dict) -> DriverCard:
        """把 PG 行还原成 DriverCard（credentials/policy 交由契约归一）。"""
        spec = payload.get("spec") or {}
        return coerce_card(
            DriverCard(
                name=str(payload.get("name") or ""),
                protocol=str(payload.get("protocol") or ""),
                endpoint=dict(spec.get("endpoint") or {}),
                config=dict(spec.get("config") or {}),
                credentials=dict(spec.get("credentials") or {}),
                enabled=bool(payload.get("enabled", True)),
                policy=payload.get("policy") or {},
            ),
        )

    async def _mirror_card_to_pg(self, card: DriverCard) -> None:
        """把驱动卡镜像到 PG 权威平面；无 PG 时跳过，PG 异常仅告警不阻塞。

        与账号/模型槽位平面一致：PG 平面绝不阻塞主链路——表未迁移/临时
        不可用时回退纯文件投影（读侧 PG 优先 + 回退文件，自洽），保证
        未迁移环内与 json 后端行为不变。
        """
        store = get_driver_pg_store()
        if store is None:
            return
        payload = self._card_to_payload(card)
        try:
            await store.upsert_card(
                self._agent_id(),
                name=payload["name"],
                protocol=payload["protocol"],
                enabled=payload["enabled"],
                spec=payload["spec"],
                policy=payload["policy"],
            )
        except Exception as exc:  # noqa: BLE001 - PG 不阻塞，回退文件投影
            logger.warning(
                "Driver card PG upsert failed, file projection kept: "
                "%s/%s: %s",
                self._agent_id(),
                card.name,
                exc,
            )

    async def _remove_card_in_pg(self, name: str) -> None:
        """从 PG 权威平面删除驱动卡（无 PG 跳过，失败仅告警）。"""
        store = get_driver_pg_store()
        if store is None:
            return
        try:
            await store.delete_card(self._agent_id(), name)
        except Exception as exc:  # noqa: BLE001 - 删除尽力而为
            logger.warning(
                "Driver card PG delete failed: %s/%s: %s",
                self._agent_id(),
                name,
                exc,
            )

    async def _load_card_from_pg(
        self,
        name: str,
        *,
        protocol: str,
    ) -> DriverCard | None:
        """优先从 PG 读一张卡；无 PG/无行/异常均返回 None 以回退文件。"""
        store = get_driver_pg_store()
        if store is None:
            return None
        try:
            row = await store.get_card(
                self._agent_id(),
                name,
                protocol=protocol,
            )
        except Exception as exc:  # noqa: BLE001 - 读优先回退文件，绝不阻塞
            logger.warning(
                "Driver card PG read failed, fallback to file: %s/%s: %s",
                self._agent_id(),
                name,
                exc,
            )
            return None
        return self._payload_to_card(row) if row else None

    async def load_card(self, name: str, *, protocol: str) -> DriverCard:
        card = await self._load_card_from_pg(name, protocol=protocol)
        if card is not None:
            return card
        path = self.card_path(name, protocol=protocol)
        if not await asyncio.to_thread(path.is_file):
            raise HTTPException(
                404,
                detail=f"{protocol.upper()} client '{name}' not found",
            )
        card = await self.card_store.load_path(path)
        if card.protocol != protocol:
            raise HTTPException(
                404,
                detail=f"{protocol.upper()} client '{name}' not found",
            )
        return card

    async def list_cards(
        self,
        *,
        protocol: str | None = None,
    ) -> list[DriverCard]:
        store = get_driver_pg_store()
        if store is not None:
            try:
                rows = await store.list_cards(
                    self._agent_id(),
                    protocol=protocol,
                )
            except Exception as exc:  # noqa: BLE001 - 读优先回退文件
                logger.warning(
                    "Driver cards PG list failed, fallback to file: %s",
                    exc,
                )
                rows = None
            if rows is not None:
                return sorted(
                    (self._payload_to_card(row) for row in rows),
                    key=lambda item: item.name,
                )
        cards: dict[str, DriverCard] = {}
        for path in await self.card_store.list_paths():
            try:
                card = await self.card_store.load_path(path)
            except Exception as exc:
                logger.warning("Failed to load DriverCard %s: %s", path, exc)
                continue
            if protocol is not None and card.protocol != protocol:
                continue
            cards[card.name] = card
        return sorted(cards.values(), key=lambda item: item.name)

    async def load_optional_credential(
        self,
        ref: str,
    ) -> CredentialRecord | None:
        if not ref:
            return None
        record = await self._load_credential_from_pg(ref)
        if record is not None:
            return record
        try:
            return await self.credential_store.get(ref)
        except CredentialNotFoundError:
            return None

    async def _load_credential_from_pg(
        self,
        ref: str,
    ) -> CredentialRecord | None:
        """优先从 PG 读凭据；无 PG/无行/异常均返回 None 以回退文件。"""
        store = get_driver_pg_store()
        if store is None:
            return None
        try:
            row = await store.get_credential(self._agent_id(), ref)
        except Exception as exc:  # noqa: BLE001 - 读优先回退文件，绝不阻塞
            logger.warning(
                "Driver credential PG read failed, fallback to file: %s: %s",
                ref,
                exc,
            )
            return None
        if not row:
            return None
        return CredentialRecord(
            ref=str(row.get("ref") or ref),
            kind=str(row.get("kind") or ""),
            public=dict(row.get("public") or {}),
            secrets=dict(row.get("secrets") or {}),
            meta=dict(row.get("meta") or {}),
        )

    async def save_credential(self, record: CredentialRecord) -> None:
        """写凭据：PG 权威镜像（best-effort）+ 文件投影；env: 引用只走文件。"""
        store = get_driver_pg_store()
        if store is not None:
            try:
                await store.put_credential(self._agent_id(), asdict(record))
            except Exception as exc:  # noqa: BLE001 - PG 不阻塞，回退文件投影
                logger.warning(
                    "Driver credential PG put failed, file projection kept: "
                    "%s/%s: %s",
                    self._agent_id(),
                    record.ref,
                    exc,
                )
        await self.credential_store.put(record)

    async def delete_credential(self, ref: str) -> None:
        """删凭据：PG + 文件双平面同步删除。"""
        store = get_driver_pg_store()
        if store is not None:
            try:
                await store.delete_credential(self._agent_id(), ref)
            except Exception as exc:  # noqa: BLE001 - 删除尽力而为
                logger.warning(
                    "Driver credential PG delete failed: %s/%s: %s",
                    self._agent_id(),
                    ref,
                    exc,
                )
        await self.credential_store.delete(ref)

    async def backfill_to_pg(self) -> int:
        """一次性回填：把文件平面的存量驱动卡与凭据种入 PG 权威平面。

        仅在 PG 已配置且本员工在 PG 尚无任何卡时执行（避免覆盖更新的 PG
        权威数据）；整段 best-effort，任何异常只告警不阻塞启动。
        返回种入的卡数；无 PG / 已有卡 / 失败均返回 0。
        """
        store = get_driver_pg_store()
        if store is None:
            return 0
        agent_id = self._agent_id()
        try:
            if await store.has_any_cards(agent_id):
                return 0
            seeded = 0
            for path in await self.card_store.list_paths():
                try:
                    card = await self.card_store.load_path(path)
                except Exception:  # noqa: BLE001 - 单张坏卡不阻断回填
                    logger.warning("Backfill skip unreadable card: %s", path)
                    continue
                payload = self._card_to_payload(card)
                await store.upsert_card(
                    agent_id,
                    name=payload["name"],
                    protocol=payload["protocol"],
                    enabled=payload["enabled"],
                    spec=payload["spec"],
                    policy=payload["policy"],
                )
                seeded += 1
            for ref in await self.credential_store.list_refs():
                try:
                    record = await self.credential_store.get(ref)
                except Exception:  # noqa: BLE001 - 单条凭据读失败跳过
                    logger.warning(
                        "Backfill skip unreadable credential: %s",
                        ref,
                    )
                    continue
                await store.put_credential(agent_id, asdict(record))
            return seeded
        except Exception as exc:  # noqa: BLE001 - 回填绝不阻塞启动
            logger.warning(
                "Driver plane PG backfill failed for %s: %s",
                agent_id,
                exc,
            )
            return 0

    async def save_card(
        self,
        card: DriverCard,
        *,
        reload_driver: bool = True,
    ) -> Path:
        # PG 权威先行（无 PG 时零动作），再写文件投影，最后热加载运行时
        await self._mirror_card_to_pg(card)
        path = await self.card_store.save(card)
        if reload_driver:
            await self.reload_driver_best_effort(card.name)
        return path

    async def save_policy(self, card: DriverCard) -> Path:
        """Persist policy changes and update the active Driver immediately."""
        # PG 权威先行（策略变更也落库），再走运行时/文件投影
        await self._mirror_card_to_pg(card)
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is not None:
            await manager.sync_driver_policy(card)
        else:
            await self.card_store.save(card)
        return self.card_path(card.name, protocol=card.protocol)

    async def reload_driver_best_effort(self, name: str) -> None:
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is None:
            return

        async def reload_background() -> None:
            try:
                await manager.reload_driver(name)
                logger.info("Driver '%s' reloaded and active", name)
            except Exception as exc:
                logger.info(
                    "Driver '%s' saved but not active yet: %s",
                    name,
                    exc,
                )

        task = asyncio.create_task(
            reload_background(),
            name=f"driver-reload:{name}",
        )
        self._reload_tasks.add(task)
        task.add_done_callback(self._reload_tasks.discard)

    async def delete_driver_best_effort(self, name: str) -> None:
        manager = getattr(self._workspace, "driver_manager", None)
        # PG 权威平面同步删除（无论运行时删除成否，配置层都应移除）
        await self._remove_card_in_pg(name)
        if manager is not None:
            try:
                await manager.delete_driver(name)
                return
            except Exception as exc:
                logger.info(
                    "Failed to delete active Driver '%s': %s",
                    name,
                    exc,
                )
        await self.card_store.delete(name)

    async def ensure_driver_active(self, name: str, *, protocol: str) -> None:
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is None:
            raise HTTPException(
                503,
                detail=_MANAGER_NOT_READY_DETAIL,
            )
        drivers = await manager.list_drivers(protocol=protocol)
        current = next(
            (item for item in drivers if item.name == name),
            None,
        )
        if current is None or current.status != "active":
            status = current.status if current is not None else "missing"
            raise HTTPException(
                503,
                detail=(
                    f"{protocol.upper()} client '{name}' is saved but not "
                    f"active yet (status={status})"
                ),
            )

    async def list_driver_capabilities(
        self,
        name: str,
        *,
        protocol: str,
        kind: str,
        request_context: dict[str, str] | None = None,
    ) -> list[Any]:
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is None:
            raise HTTPException(
                503,
                detail=_MANAGER_NOT_READY_DETAIL,
            )
        await self.ensure_driver_active(name, protocol=protocol)
        return await manager.list_driver_capabilities(
            name,
            kind=kind,
            request_context=request_context or {},
        )


async def ensure_driver_active(
    manager: Any,
    name: str,
    *,
    protocol: str,
) -> DriverRuntimeInfo:
    """Compatibility helper for tests and small call sites."""
    drivers = await manager.list_drivers(protocol=protocol)
    current = next((item for item in drivers if item.name == name), None)
    if current is None or current.status != "active":
        status = current.status if current is not None else "missing"
        raise HTTPException(
            503,
            detail=(
                f"{protocol.upper()} client '{name}' is saved but not "
                f"active yet (status={status})"
            ),
        )
    return current
