# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the model enable/disable switch (disabled_model_ids)."""
from __future__ import annotations

import pytest

from qwenpaw.exceptions import ProviderError
from qwenpaw.providers.provider_manager import ProviderManager


@pytest.fixture
def manager():
    """Fresh ProviderManager over the isolated secret dir (conftest)."""
    return ProviderManager()


class TestDisabledModelIds:
    def test_configured_models_filters_disabled(self, manager) -> None:
        """disabled 模型保留配置但从 configured_models 隐藏。"""
        provider = manager.get_provider("dashscope")
        assert provider is not None
        catalog_ids = [m.id for m in provider.models]
        if not catalog_ids:  # pragma: no cover - 目录异常时跳过
            pytest.skip("dashscope catalog empty")
        target = catalog_ids[0]

        provider.disabled_model_ids = [target]
        configured = {m.id for m in provider.configured_models()}
        assert target not in configured

        # 重新启用后恢复
        provider.disabled_model_ids = []
        configured = {m.id for m in provider.configured_models()}
        assert target in configured

    def test_disabled_keeps_config_in_by_id(self, manager) -> None:
        """禁用不影响 get_model_info（配置保留语义）。"""
        provider = manager.get_provider("dashscope")
        assert provider is not None
        target = next(iter(provider.models), None)
        if target is None:  # pragma: no cover
            pytest.skip("dashscope catalog empty")

        provider.disabled_model_ids = [target.id]
        assert provider.get_model_info(target.id) is not None

    async def test_set_model_disabled_roundtrip(self, manager) -> None:
        """manager.set_model_disabled 持久化到快照并可恢复。"""
        provider = manager.get_provider("dashscope")
        assert provider is not None
        target = next(iter(provider.models), None)
        if target is None:  # pragma: no cover
            pytest.skip("dashscope catalog empty")

        # 隔离环境无真实 Key：塞入临时 Key 以通过启用方向守卫
        original_key = provider.api_key
        original_require = provider.require_api_key
        provider.api_key = "sk-test"
        provider.require_api_key = True
        try:
            await manager.set_model_disabled(
                "dashscope",
                target.id,
                disabled=True,
            )
            current = manager.get_provider("dashscope")
            assert current is not None
            assert target.id in current.disabled_model_ids
            assert all(
                m.id != target.id for m in current.configured_models()
            )

            await manager.set_model_disabled(
                "dashscope",
                target.id,
                disabled=False,
            )
            current = manager.get_provider("dashscope")
            assert current is not None
            assert target.id not in current.disabled_model_ids
        finally:
            provider.api_key = original_key
            provider.require_api_key = original_require

    async def test_disabled_survives_manager_restart(self, manager) -> None:
        """重启（重建 manager）后禁用状态必须保留。

        回归：_restore_builtin_provider 曾恢复 hidden/removed 却漏掉
        disabled_model_ids，导致重启后禁用模型回到启用态。
        """
        provider = manager.get_provider("dashscope")
        assert provider is not None
        target = next(iter(provider.models), None)
        if target is None:  # pragma: no cover
            pytest.skip("dashscope catalog empty")

        # 隔离环境无真实 Key：塞入临时 Key 以通过启用方向守卫
        original_key = provider.api_key
        original_require = provider.require_api_key
        provider.api_key = "sk-test"
        provider.require_api_key = True
        try:
            await manager.set_model_disabled(
                "dashscope", target.id, disabled=True,
            )
            # 模拟重启：基于同一隔离 secret dir 重建 manager
            restarted = ProviderManager()
            current = restarted.get_provider("dashscope")
            assert current is not None
            assert target.id in current.disabled_model_ids
            assert all(
                m.id != target.id for m in current.configured_models()
            )
        finally:
            provider.api_key = original_key
            provider.require_api_key = original_require

    async def test_cannot_enable_model_without_provider_key(
        self,
        manager,
    ) -> None:
        """厂商需要 Key 且未配置时，启用模型被拒绝（防误导性“已启用”）。"""
        provider = manager.get_provider("dashscope")
        assert provider is not None
        target = next(iter(provider.models), None)
        if target is None:  # pragma: no cover
            pytest.skip("dashscope catalog empty")

        original_key = provider.api_key
        original_require = provider.require_api_key
        try:
            provider.api_key = ""
            provider.require_api_key = True
            with pytest.raises(ProviderError):
                await manager.set_model_disabled(
                    "dashscope",
                    target.id,
                    disabled=False,
                )
            # 禁用方向不受守卫限制
            await manager.set_model_disabled(
                "dashscope", target.id, disabled=True,
            )
            current = manager.get_provider("dashscope")
            assert current is not None
            assert target.id in current.disabled_model_ids
        finally:
            provider.api_key = original_key
            provider.require_api_key = original_require
