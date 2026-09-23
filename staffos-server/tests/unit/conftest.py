# -*- coding: utf-8 -*-
"""unit 层宿主机部署态隔离防波堤。

单测语义 = 零外部依赖、确定性。但开发者宿主机往往长期携带部署态：

1. 环境变量渗入：``QWENPAW_PG_DSN`` / ``QWENPAW_STORAGE_BACKEND=pg``
   （评测/联调残留）会让假设默认 file 后端的用例静默改走 pg 判定；
2. 认证态渗入：多用户部署把 config 的 ``security.auth_enabled`` 打开，
   ``rbac.deps.rbac_enforcement_enabled`` 未显式配置时**跟随认证开关**，
   存量单测的无身份请求随即被 fail-closed 403（测试各自 patch 的包
   re-export 别名打不到 deps/auth 模块全局，且 routers/auth 等处为
   顶层绑定引用，逐模块 patch 不可维护）。

本 conftest 以 autouse fixture 在**输入级**钉死「单机免认证 + 默认存储」
基线（env 清理 + auth 配置单例置 False——``is_auth_enabled`` 与 rbac
deps 的延迟导入都收敛到这个输入）；需要反向行为（pg / 认证开启）的
用例在自己的 monkeypatch 里显式设置（用例级操作晚于 autouse 应用，
正常覆盖；``QWENPAW_RBAC_ENFORCE`` 等显式 env 分支位于 fallback 之前，
专测 env 的用例不受影响）。

另提供 :func:`require_symlink`——Windows 无
``SeCreateSymbolicLinkPrivilege``（非管理员且未开开发者模式）时
``Path.symlink_to`` 报 WinError 1314，符号链接语义用例按能力跳过。

@author qingfeng
"""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def unit_host_env_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主机 env 与认证态，恢复单测确定性基线。"""
    # 宿主机长期部署 env（评测/联调残留）——单测一律按未设置处理
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_KB_DEFAULT_ENGINE", raising=False)
    # 认证/RBAC 显式开关同样归零（显式分支优先于 fallback，必须先清）
    monkeypatch.delenv("QWENPAW_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("QWENPAW_RBAC_ENFORCE", raising=False)

    # storage backend 双检锁缓存可能已被同进程先前用例写入宿主判定，
    # 逐用例清空保证 delenv 真正生效（函数本身零网络零副作用）
    from qwenpaw.db import write_gateway

    write_gateway.reset_backend_cache()

    # 认证态在**输入级**钉死：is_auth_enabled 未设 env 时读 config 单例
    # 的 security.auth_enabled；auth/rbac/routers-auth 等全部消费方
    # （含顶层绑定引用）都收敛到这一个输入，置 False 即全局单机态。
    import qwenpaw.app.auth as auth_mod

    cfg, _networks = auth_mod._get_config_cached()
    monkeypatch.setattr(cfg.security, "auth_enabled", False, raising=False)


def _symlink_supported() -> bool:
    """Probe whether the current process may create symbolic links."""
    probe = Path(tempfile.mkdtemp(prefix="qwenpaw_symlink_probe_"))
    try:
        target = probe / "t"
        target.write_text("x", encoding="utf-8")
        (probe / "l").symlink_to(target)
        return True
    except OSError:
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


_SYMLINK_OK = _symlink_supported()


@pytest.fixture
def require_symlink() -> None:
    """Skip symlink-semantics tests where links cannot be created."""
    if not _SYMLINK_OK:
        pytest.skip(
            "symbolic links unavailable (Windows without "
            "SeCreateSymbolicLinkPrivilege / developer mode)",
        )
