# -*- coding: utf-8 -*-
"""检索引擎命中读模型（``KbSearchHit``）。

独立于 ``engine.py`` 存在的理由（环防护）：``engine.py`` 顶层反向依赖三个
实现模块（工厂构造 + 重导出），而三个实现模块需要构造本类型作为 ``search``
的返回值。把本类型放在这里，依赖图收敛为
``engine → 实现模块 → hits`` 单向链；``engine.py`` 仍以
``from .hits import KbSearchHit`` 重导出，对外契约面
（``engine.KbSearchHit``）不变。

字段契约（Task 5 产出，Task 9/10 的检索与溯源消费）：

- ``parent_seq``：同节父块（节首块）的 ``seq``，无父块为 ``None``；
  语义由 Task 3 切片器定义（**同节所有非首块指向节首块**），
  pg/milvus 引擎由 ``parent_chunk_id`` 反解回填，文件引擎无此列恒为 ``None``。

@author qingfeng
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class KbSearchHit:
    """一条 chunk 级检索命中（引擎无关的统一读模型）。"""

    space_id: str
    document_id: str
    chunk_id: str
    seq: int
    heading_path: str
    text: str
    score: float
    parent_seq: Optional[int] = None


__all__ = [
    "KbSearchHit",
]
