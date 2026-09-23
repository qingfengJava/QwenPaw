# -*- coding: utf-8 -*-
"""TrustedExecutionEnvelope 进程内签名（T4：外部请求自填无效）。

信封随委派请求经 /console/chat 的 ``request_context`` 传输。为满足
协议02"服务端控制面可信载荷、外部请求自填无效"的约束，委派发起侧
以进程级密钥对信封做 HMAC-SHA256 签名，工具治理侧验签通过才承认其
授权语义：外部伪造的请求（未持密钥）一律判定为篡改（fail-closed）。

密钥仅在进程内存活（``secrets.token_bytes`` 惰性生成），随服务重启
轮换；同进程内的 workforce（签名方）与 governance（验签方）共享
同一密钥——签名防的是跨进程/跨网络的外部伪造，不防同进程代码
（同进程代码本身即在信任边界内）。

@author qingfeng
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from typing import Any, Dict

#: 签名前缀（算法版本号，便于未来轮换签名算法）
_SIG_PREFIX = "v1:"

_lock = threading.Lock()
_secret: bytes = b""


def _signing_secret() -> bytes:
    """获取（首次惰性生成的）进程级信封签名密钥。"""
    global _secret
    with _lock:
        if not _secret:
            _secret = secrets.token_bytes(32)
        return _secret


def canonical_envelope_bytes(payload: Dict[str, Any]) -> bytes:
    """信封规范序列化（排序键 + 紧凑分隔符，保证签名确定性）。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_envelope_payload(payload: Dict[str, Any]) -> str:
    """对信封载荷签名（返回 ``v1:<hex>`` 形式的签名字符串）。"""
    # 规范序列化后以进程密钥计算 HMAC-SHA256
    digest = hmac.new(
        _signing_secret(),
        canonical_envelope_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    return _SIG_PREFIX + digest


def verify_envelope_payload(payload: Dict[str, Any], signature: str) -> bool:
    """验签（常数时间比较；任何形态异常一律按不匹配处理）。"""
    # 签名格式与类型前置校验（异常形态直接不匹配）
    if not isinstance(signature, str) or not signature.startswith(_SIG_PREFIX):
        return False
    # 期望值按同一规范序列化重算，常数时间比较防时序侧信道
    expected = sign_envelope_payload(payload)
    return hmac.compare_digest(expected, signature)
