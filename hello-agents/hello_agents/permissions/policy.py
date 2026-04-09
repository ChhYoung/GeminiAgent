"""
permissions/policy.py — 权限策略定义 (s07)

三级策略：
  default  每次执行危险工具都询问用户
  auto     启发式判断，安全工具直通，危险工具询问
  bypass   全部直通（开发/测试用）
"""

from __future__ import annotations

from enum import Enum


class PermissionPolicy(str, Enum):
    DEFAULT = "default"   # 危险操作必须询问
    AUTO    = "auto"      # 启发式：安全工具直通，危险工具询问
    BYPASS  = "bypass"    # 全部直通（开发用）

    # 被永久拒绝的工具（不受 bypass 影响）需通过 deny_list 单独控制

    @classmethod
    def from_str(cls, s: str) -> "PermissionPolicy":
        try:
            return cls(s.lower())
        except ValueError:
            return cls.DEFAULT
