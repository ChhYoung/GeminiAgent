"""
examples/basic_chat.py — 基础对话示例

演示如何使用 HelloAgent 进行带记忆的多轮对话。

运行前：
    1. cp .env.example .env  并填入 GEMINI_API_KEY
    2. 启动 Qdrant: docker run -p 6333:6333 qdrant/qdrant
    3. 启动 Neo4j:  docker run -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j
    4. pip install -e .
    5. python examples/basic_chat.py
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from hello_agents.agent import HelloAgent


async def main():
    print("初始化 Agent...")
    agent = HelloAgent.from_env(model="gemini-1.5-flash")
    await agent.start()

    session_id = "demo_session"
    print("\n=== HelloAgent 对话示例（输入 'quit' 退出）===\n")

    try:
        while True:
            user_input = input("你: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            response = await agent.chat(user_input, session_id=session_id)
            print(f"\nAgent: {response}\n")

    finally:
        print("\n正在关闭 Agent...")
        await agent.stop()
        print("再见！")


if __name__ == "__main__":
    asyncio.run(main())
