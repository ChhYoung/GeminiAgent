"""
examples/memory_demo.py — 记忆系统独立演示

无需启动完整 Agent，直接演示记忆写入、检索、遗忘曲线。

运行：
    GEMINI_API_KEY=xxx QDRANT_URL=http://localhost:6333 python examples/memory_demo.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from hello_agents.memory.manager import MemoryManager
from hello_agents.memory.base import ImportanceLevel, MemoryType


async def main():
    print("初始化记忆管理器（仅 Episodic + Semantic）...\n")

    manager = MemoryManager.from_env(enable_reflection=False)
    await manager.start()

    session_id = "memory_demo"

    # ---- 写入情景记忆 ----
    print("写入 3 条情景记忆...")
    ids = []
    for content, imp in [
        ("用户小明今天下午3点开会，讨论了 Q2 项目计划", ImportanceLevel.HIGH),
        ("用户提到他最近在学习 Rust 编程语言", ImportanceLevel.MEDIUM),
        ("今天天气很好，用户心情不错", ImportanceLevel.LOW),
    ]:
        r = manager.write(
            content=content,
            memory_type=MemoryType.EPISODIC,
            importance=imp,
            session_id=session_id,
        )
        ids.append(r.id)
        print(f"  ✓ [{imp.value:8s}] {content[:40]}...")

    print()

    # ---- 检索记忆 ----
    print("检索：'项目会议安排'")
    results = manager.read("项目会议安排", session_id=session_id, top_k=3)
    for r in results:
        print(
            f"  [{r.record.memory_type.value}] score={r.final_score:.3f} "
            f"strength={r.record.strength:.2f}\n"
            f"    {r.record.content[:60]}"
        )

    print()

    # ---- 工作记忆 ----
    print("工作记忆（对话窗口）演示...")
    wm = manager.get_working_memory(session_id)
    wm.add("你好，我想了解一下最近的会议安排", metadata={"role": "user"})
    wm.add("好的，根据您的记录，您今天下午3点有一个会议", metadata={"role": "assistant"})
    wm.add("谢谢，会议的主要议题是什么？", metadata={"role": "user"})
    print("  当前对话窗口：")
    print(wm.to_context_string())

    print()

    # ---- 触发反思 ----
    print("手动触发反思（Episodic -> Semantic）...")
    new_ids = await manager.reflect(session_id=session_id)
    print(f"  生成了 {len(new_ids)} 条语义记忆")

    # ---- 统计 ----
    stats = manager.stats()
    print(f"\n记忆统计: {stats}")

    await manager.stop()
    print("\n完成！")


if __name__ == "__main__":
    asyncio.run(main())
