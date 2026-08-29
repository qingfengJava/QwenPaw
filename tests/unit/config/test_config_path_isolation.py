# -*- coding: utf-8 -*-
"""config.utils 的 WORKING_DIR 动态解析回归测试（测试隔离根因修复）。

背景：``config/utils.py`` 曾以 ``from ..constant import WORKING_DIR``
导入期绑定路径常量——builtin 专家 seeding 测试 monkeypatch
``constant.WORKING_DIR`` 后，publish 链的 ``load_config/save_config``
仍指向真实用户目录，把 pytest 临时 workspace 路径写进了用户真实的
``~/.copaw/config.json``（真实事故：builtin agent profile 全部指向
pytest tmp，运行时 channel_manager 服务缺失，A2A 委派 500）。

本文件锁定：config 路径解析必须跟随 constant.WORKING_DIR 的**当前值**
（模块属性动态读取），测试替换工作区时配置读写完全隔离。

@author qingfeng
"""
from __future__ import annotations

from pathlib import Path

pytest_plugins: list[str] = []


def test_config_path_follows_patched_working_dir(monkeypatch, tmp_path):
    """monkeypatch constant.WORKING_DIR 后，config/jobs/chats 路径必须
    全部落入临时工作区（隔离生效，不触碰真实用户目录）。"""
    from qwenpaw.config import utils as config_utils

    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR", Path(tmp_path), raising=True
    )
    # config.json 与派生路径全部跟随替换后的工作区
    assert config_utils.get_config_path() == Path(tmp_path) / "config.json"
    assert (
        config_utils.get_jobs_path().parent == Path(tmp_path)
    )
    assert (
        config_utils.get_chats_path().parent == Path(tmp_path)
    )


def test_config_path_default_is_user_working_dir():
    """未替换时解析到真实工作区（回归保护：动态读取没有破坏默认行为）。"""
    from qwenpaw.config import utils as config_utils
    from qwenpaw.constant import WORKING_DIR

    assert config_utils.get_config_path() == WORKING_DIR / "config.json"
