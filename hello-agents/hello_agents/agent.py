"""
agent.py — OpenAI-compatible Agent 主体

将记忆系统、RAG 工具、上下文组装和多轮对话管理整合为可直接运行的 Agent。

核心能力：
1. 多轮对话（工作记忆维护对话窗口）
2. 自动将重要信息存入情景/语义记忆
3. 使用 ContextBuilder (GSSC) 组装每轮上下文 (s05: 知识按需注入)
4. 支持 Function Calling（统一 ToolRegistry 调度）(s02)
5. 后台反思引擎定期巩固记忆
6. 可选 Planner 在复杂任务前先列步骤 (s03)
7. 任务管理、后台执行、Agent 间通信工具 (s07/s08/s09)

架构原则 (s01): _generate_with_tools 是唯一循环，所有能力通过
              往 ToolRegistry 加 handler 扩展，循环本身不变。
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
from hello_agents.tools.builtin.task_tool import TASK_TOOLS, TaskToolHandler
from hello_agents.tools.builtin.background_tool import BACKGROUND_TOOLS, BackgroundToolHandler
from hello_agents.tools.builtin.agent_tool import AGENT_TOOLS, AgentToolHandler
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tasks.scheduler import Scheduler
from hello_agents.tasks.store import TaskStore
from hello_agents.tasks.background import BackgroundExecutor
from hello_agents.multi_agent.mailbox import Mailbox

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
7. 创建和跟踪任务，支持依赖关系
8. 后台执行耗时操作，不阻塞当前对话
9. 与其他专业 Agent 协作完成复杂任务

当你需要回忆过去的对话信息时，使用 search_memory 工具。
当你需要查阅参考文档时，使用 search_knowledge 工具。
当你发现重要信息需要记住时，主动使用 store_memory 工具。
当需要记录结构化信息时，使用笔记工具（create_note/list_notes）。
当需要实时信息时，使用 web_search 工具。
当任务复杂时，使用 create_task 拆分子任务并跟踪进度。
当操作耗时时，使用 run_background 异步执行。

请始终保持友好、专业的对话风格，用中文回复（除非用户使用其他语言）。
""".strip()


class HelloAgent:
    """
    OpenAI-compatible Agent 主类。

    s01: _generate_with_tools 是唯一的 tool-calling loop，≤20 行。
    s02: 新工具只需 register_handler，不改 loop。
    s03: use_planner=True 时先调用 Planner 拆解步骤再执行。

    用法：
        agent = HelloAgent.from_env()
        await agent.start()
        response = await agent.chat("你好，我叫小明", session_id="user_001")
        await agent.stop()
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        kb_manager: KnowledgeBaseManager,
        system_prompt: str = _SYSTEM_PROMPT,
        max_tool_rounds: int = 5,
    ) -> None:
        cfg = get_settings()
        self._memory = memory_manager
        self._kb = kb_manager
        self.system_prompt = system_prompt
        self._max_tool_rounds = max_tool_rounds

        self._client = openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        self._model = cfg.llm_model_id

        self._ctx_builder = ContextBuilder(
            memory_manager=memory_manager,
            kb_manager=kb_manager,
        )
        self._registry = ToolRegistry()

    @classmethod
    def from_env(
        cls,
        enable_reflection: bool = True,
        agent_id: str = "main",
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

        # s02: 每个新工具只需加一个 handler，loop 不动
        agent._registry.register_handler(MemoryToolHandler(memory), MEMORY_TOOLS)
        agent._registry.register_handler(RAGToolHandler(kb_manager), RAG_TOOLS)
        agent._registry.register_handler(NoteToolHandler(), NOTE_TOOLS)
        agent._registry.register_handler(TerminalToolHandler(), TERMINAL_TOOLS)
        agent._registry.register_handler(WebSearchToolHandler(), WEB_SEARCH_TOOLS)

        # s07: 任务管理工具
        scheduler = Scheduler(store=TaskStore())
        agent._registry.register_handler(TaskToolHandler(scheduler), TASK_TOOLS)

        # s08: 后台执行工具
        executor = BackgroundExecutor()
        agent._registry.register_handler(BackgroundToolHandler(executor), BACKGROUND_TOOLS)

        # s09/s10: Agent 间通信工具
        mailbox = Mailbox()
        agent._registry.register_handler(AgentToolHandler(agent_id, mailbox), AGENT_TOOLS)

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

        s05: 记忆/知识通过 tool_result 按需注入，
             system prompt 只保留 pinned 历史摘要。
        """
        wm = self._memory.get_working_memory(session_id)

        # 历史对话窗口（工作记忆）
        history_str = wm.to_context_string(last_n=10)

        # s05: 只在 include_context=True 且有 pinned 摘要时注入少量上下文
        context_str = ""
        if include_context:
            try:
                context_str = await self._ctx_builder.build(
                    query=user_message, session_id=session_id
                )
            except Exception as exc:
                logger.warning("ContextBuilder failed: %s", exc)

        # 组装 system prompt（≤500 token 的固定部分 + 少量 pinned 上下文）
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

        # s01: 唯一循环
        response_text = await self._generate_with_tools(messages, session_id=session_id)

        # 记录 Assistant 回复到工作记忆
        wm.add(
            response_text,
            metadata={"role": "assistant"},
            importance=ImportanceLevel.LOW,
        )

        # 异步将对话存入情景记忆
        _bg = asyncio.ensure_future(
            self._store_episodic_async(user_message, response_text, session_id)
        )
        _ = _bg  # suppress GC warning

        return response_text

    # ------------------------------------------------------------------
    # s01: 唯一 tool-calling 循环（保持 ≤20 行）
    # ------------------------------------------------------------------

    async def _generate_with_tools(
        self, messages: list[dict], session_id: str = "default"
    ) -> str:
        """调用 OpenAI SDK，处理多轮 Function Calling。(s01)"""
        tool_schemas = self._registry.get_schemas()
        current_messages = list(messages)

        for _ in range(self._max_tool_rounds):
            response = await self._call_llm(current_messages, tool_schemas)
            message = response.choices[0].message

            if message.tool_calls:
                current_messages.append(message.model_dump())
                for tc in message.tool_calls:
                    current_messages.append(self._run_one_tool(tc))
            else:
                return message.content or ""

        return message.content or ""  # type: ignore[possibly-undefined]

    async def _call_llm(
        self, messages: list[dict], tool_schemas: list[dict]
    ) -> Any:
        """向 LLM 发起一次请求（包装为 async）。"""
        return await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            messages=messages,
            tools=tool_schemas if tool_schemas else openai.NOT_GIVEN,
            temperature=0.7,
            max_tokens=2048,
        )

    def _run_one_tool(self, tool_call: Any) -> dict:
        """执行单个工具调用，返回 tool message dict。(s02)"""
        result = self._registry.dispatch(tool_call)
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

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
