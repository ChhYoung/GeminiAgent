"""
recovery/retry.py — 指数退避重试策略 (s11)
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Type

logger = logging.getLogger(__name__)


class RetryPolicy:
    """
    指数退避重试。

    用法：
        policy = RetryPolicy(max_attempts=3, retryable=(TimeoutError,))
        result = await policy.execute(my_async_fn, arg1, arg2)
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True,
        retryable: tuple[Type[Exception], ...] = (Exception,),
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.retryable = retryable

    async def execute(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        执行 fn（可以是 async 或 sync），失败时按策略重试。

        Raises:
            最后一次失败的异常（若所有重试均失败）
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except self.retryable as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    break
                delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                if self.jitter:
                    delay *= 0.5 + random.random() * 0.5
                logger.warning(
                    "Attempt %d/%d failed (%s). Retrying in %.1fs…",
                    attempt, self.max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]

    def with_attempts(self, n: int) -> "RetryPolicy":
        """返回调整了 max_attempts 的新实例。"""
        return RetryPolicy(
            max_attempts=n,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            jitter=self.jitter,
            retryable=self.retryable,
        )
