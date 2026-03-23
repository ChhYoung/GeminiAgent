"""
agent.py — OpenAI-compatible Agent 主体

将记忆系统、RAG 工具、上下文组装和多轮对话管理整合为可直接运行的 Agent。

核心能力：
1. 多轮对话（工作记忆维护对话窗口）
2. 自动将重要信息存入情景/语义记忆
3. 使用 ContextBuilder (GSSC) 组装每轮上下文
4. 支持 Function Calling（统一 ToolRegistry 调度）
5. 后台反思引擎定期巩固记忆
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import openai
from dotenv import load_dotenv

from hello_agents.config import get_settings
from hello_agents.context.builder import ContextBuilder
from hello_agents.memory.base import ImportanceLevel, MemoryType
from hello_agents.memory.manager import MemoryManager
from hello_agents.rag.knowledge_base import KnowledgeBaseManager
from hello_agents.rag.pipeline import RAGPipeline
from hello_agents.tools.builtin.memory_tool import MEMORY_TOOLS, MemoryToolHandler
from hello_agents.tools.builtin.note_tool import NOTE_TOOLS, NoteToolHandler
from hello_agents.tools.builtin.rag_tool import RAG_TOOLS, RAGToolHandler
from hello_agents.tools.builtin.terminal_tool import TERMINAL_TOOLS, TerminalToolHandler
from hello_agents.tools.builtin.web_search_tool import WEB_SEARCH_TOOLS, WebSearchToolHandler
from hello_agents.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

load_dotenv()

_SYSTEM_PROMPT = """
你是一个具备长期记忆能力的 AI 助手。你能够：
1. 记住用户在历史对话中分享的信息和偏好
2. 从外部知识库中检索参考资料
3. 主动存储重要信息以备日后使用
4. 创建和管理结构化笔记
5. 在需要时搜索互联网获取实时信息
6. 执行安全的终端命令查看系统状态

当你需要回忆过去的对话信息时，使用 search_memory 工具。
当你需要查阅参考文档时，使用 search_knowledge 工具。
当你发现重要信息需要记住时，主动使用 store_memory 工具。
当需要记录结构化信息时，使用笔记工具（create_note/list_notes）。
当需要实时信息时，使用 web_search 工具。

请始终保持友好、专业的对话风格，用中文回复（除非用户使用其他语言）。
"""


class HelloAgent:
    """
    OpenAI-compatible Agent 主类。

    用法：
        agent = HelloAgent.from_env()
        await agent.start()

        response = await agent.chat("你好，我叫小明，我喜欢写 Python", session_id="user_001")
        print(response)

        await agent.stop()
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        kb_manager: KnowledgeBaseManager,
        system_prompt: str = _SYSTEM_PROMPT,
    ) -> None:
        cfg = get_settings()
        self._memory = memory_manager
        self._kb = kb_manager
        self.system_prompt = system_prompt

        self._client = openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        self._model = cfg.llm_model_id

        # 构建上下文组装器
        self._ctx_builder = ContextBuilder(
            memory_manager=memory_manager,
            kb_manager=kb_manager,
        )

        # 构建统一工具注册表
        self._registry = ToolRegistry()

    @classmethod
    def from_env(
        cls,
        enable_reflection: bool = True,
    ) -> "HelloAgent":
        """从环境变量构建 Agent（含所有子系统）。"""
        load_dotenv()
        cfg = get_settings()

        from hello_agents.memory.embedding import EmbeddingService

        embedding = EmbeddingService()
        memory = MemoryManager.from_env(enable_reflection=enable_reflection)
        pipeline = RAGPipeline(embedding=embedding)
        kb_manager = KnowledgeBaseManager(pipeline=pipeline)

        agent = cls(memory_manager=memory, kb_manager=kb_manager)

        # 注册所有内置工具
        agent._registry.register_handler(
            MemoryToolHandler(memory), MEMORY_TOOLS
        )
        agent._registry.register_handler(
            RAGToolHandler(kb_manager), RAG_TOOLS
        )
        agent._registry.register_handler(
            NoteToolHandler(), NOTE_TOOLS
        )
        agent._registry.register_handler(
            TerminalToolHandler(), TERMINAL_TOOLS
        )
        agent._registry.register_handler(
            WebSearchToolHandler(), WEB_SEARCH_TOOLS
        )

        return agent

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        await self._memory.start()
        logger.info("HelloAgent started.")

    async def stop(self) -> None:
        await self._memory.stop()
        logger.info("HelloAgent stopped.")

    # ------------------------------------------------------------------
    # 对话接口
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_message: str,
        session_id: str = "default",
        include_context: bool = True,
    ) -> str:
        """
        单轮对话入口（内部维护多轮上下文）。

        Args:
            user_message:    用户输入
            session_id:      会话 ID（用于隔离不同用户）
            include_context: 是否注入记忆/知识上下文

        Returns:
            Assistant 回复文本
        """
        wm = self._memory.get_working_memory(session_id)

        # 构建 GSSC 上下文
        context_str = ""
        if include_context:
            try:
                context_str = await self._ctx_builder.build(
                    query=user_message, session_id=session_id
                )
            except Exception as exc:
                logger.warning("ContextBuilder failed: %s", exc)

        # 历史对话窗口
        history_str = wm.to_context_string(last_n=10)

        # 组装 system prompt（含上下文）
        system_parts = [self.system_prompt]
        if context_str:
            system_parts.append("\n\n### 相关上下文 ###\n" + context_str)
        if history_str:
            system_parts.append("\n\n### 当前对话历史 ###\n" + history_str)

        messages = [
            {"role": "system", "content": "\n".join(system_parts)},
            {"role": "user", "content": user_message},
        ]

        # 记录用户消息到工作记忆
        wm.add(user_message, metadata={"role": "user"}, importance=ImportanceLevel.MEDIUM)

        # 调用 LLM（带 Function Calling）
        response_text = await self._generate_with_tools(messages, session_id=session_id)

        # 记录 Assistant 回复到工作记忆
        wm.add(
            response_text,
            metadata={"role": "assistant"},
            importance=ImportanceLevel.LOW,
        )

        # 异步将对话存入情景记忆
        asyncio.ensure_future(
            self._store_episodic_async(user_message, response_text, session_id)
        )

        return response_text

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _generate_with_tools(
        self, messages: list[dict], session_id: str
    ) -> str:
        """调用 OpenAI SDK，处理多轮 Function Calling。"""
        tool_schemas = self._registry.get_schemas()
        max_tool_rounds = 5

        # 每轮工具调用需要维护完整的消息历史
        current_messages = list(messages)

        for _ in range(max_tool_rounds):
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=current_messages,
                tools=tool_schemas if tool_schemas else openai.NOT_GIVEN,
                temperature=0.7,
                max_tokens=2048,
            )

            choice = response.choices[0]
            message = choice.message

            # 检查是否有工具调用
            if message.tool_calls:
                # 将 assistant 消息（含 tool_calls）加入历史
                current_messages.append(message.model_dump())

                # 依次执行所有工具调用
                for tool_call in message.tool_calls:
                    tool_result = self._registry.dispatch(tool_call)
                    current_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )
            else:
                # 正常文本回复
                return message.content or ""

        # 超过最大工具轮次，返回最后的文本
        return message.content or ""

    async def _store_episodic_async(
        self, user_msg: str, assistant_msg: str, session_id: str
    ) -> None:
        """后台将对话存入情景记忆。"""
        try:
            combined = f"用户说：{user_msg}\n助手回复：{assistant_msg}"
            await asyncio.to_thread(
                self._memory.write,
                combined,
                MemoryType.EPISODIC,
                ImportanceLevel.LOW,
                {"role": "conversation"},
                session_id,
            )
        except Exception as exc:
            logger.warning("Failed to store episodic memory: %s", exc)

    # ------------------------------------------------------------------
    # 知识库便捷接口
    # ------------------------------------------------------------------

    def add_knowledge(
        self,
        kb_name: str,
        file_path: str | None = None,
        text: str | None = None,
        description: str = "",
    ) -> None:
        """向知识库中添加文档或文本。"""
        kb = self._kb.create(kb_name, description=description)
        if file_path:
            kb.add_file(file_path)
        if text:
            kb.add_text(text)
