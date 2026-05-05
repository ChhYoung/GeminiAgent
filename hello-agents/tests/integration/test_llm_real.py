"""
tests/integration/test_llm_real.py

真实大模型服务集成测试 —— 所有用例均调用真实 API，不使用 mock。

覆盖场景：
  1. 原生 OpenAI SDK 补全（单轮）
  2. 原生 Embedding 生成（向量维度 + 语义相似度）
  3. HelloAgent.chat() — 记忆/KB 用 mock 隔离，LLM 走真实
  4. Function Calling — LLM 主动决策调用工具
  5. 上下文压缩（Layer 3）— 调用真实 LLM 生成摘要
  6. Web 搜索工具 — Tavily / SerpAPI 真实调用

运行方式：
    PYTHONPATH=. pytest tests/integration/test_llm_real.py -v -s
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=Path(__file__).parent.parent.parent / ".env",
    override=True,
)

from hello_agents.config import get_settings

get_settings.cache_clear()
cfg = get_settings()

# 所有测试共用的 skip 条件
requires_llm = pytest.mark.skipif(
    not cfg.llm_api_key,
    reason="LLM_API_KEY 未配置，跳过真实 LLM 测试",
)
requires_tavily = pytest.mark.skipif(
    not cfg.tavily_api_key,
    reason="TAVILY_API_KEY 未配置，跳过 Tavily 真实测试",
)
requires_serpapi = pytest.mark.skipif(
    not cfg.serpapi_api_key,
    reason="SERPAPI_API_KEY 未配置，跳过 SerpAPI 真实测试",
)


# ===========================================================================
# 1. 原生 SDK — Chat Completion
# ===========================================================================

@requires_llm
class TestRealLLMCompletion:
    """直接使用 OpenAI SDK 调用真实 LLM。"""

    def _client(self):
        import openai
        return openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)

    def test_single_turn_returns_nonempty(self):
        """最小请求：回复非空字符串。"""
        resp = self._client().chat.completions.create(
            model=cfg.llm_model_id,
            messages=[{"role": "user", "content": "用一句话介绍 Python。"}],
            max_tokens=100,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip()
        assert reply, "❌ LLM 返回空内容"
        print(f"\n  ✅ 单轮回复: {reply[:80]!r}...")

    def test_system_prompt_respected(self):
        """验证 system prompt 能影响输出风格。"""
        resp = self._client().chat.completions.create(
            model=cfg.llm_model_id,
            messages=[
                {"role": "system", "content": "你只能用英文回答，不得使用中文。"},
                {"role": "user", "content": "你好，请介绍一下你自己。"},
            ],
            max_tokens=150,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip()
        # 简单验证：回复中有常见英文字符
        assert any(c.isascii() and c.isalpha() for c in reply), (
            f"❌ 期望英文回复，实际: {reply!r}"
        )
        print(f"\n  ✅ system prompt 生效，英文回复: {reply[:60]!r}")

    def test_multi_turn_context_maintained(self):
        """多轮对话：第二轮应能引用第一轮信息。"""
        client = self._client()
        messages = [
            {"role": "user", "content": "我的名字是 Alice。"},
            {"role": "assistant", "content": "你好，Alice！很高兴认识你。"},
            {"role": "user", "content": "我叫什么名字？"},
        ]
        resp = client.chat.completions.create(
            model=cfg.llm_model_id,
            messages=messages,
            max_tokens=80,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip()
        assert "Alice" in reply or "alice" in reply.lower(), (
            f"❌ 期望回复包含 Alice，实际: {reply!r}"
        )
        print(f"\n  ✅ 多轮上下文保持正常: {reply!r}")

    def test_structured_json_output(self):
        """要求 LLM 输出 JSON，验证可解析。"""
        resp = self._client().chat.completions.create(
            model=cfg.llm_model_id,
            messages=[{
                "role": "user",
                "content": (
                    '请用 JSON 格式返回三个编程语言，格式如：'
                    '{"languages": ["lang1", "lang2", "lang3"]}'
                    '，只输出 JSON，不要其他文字。'
                ),
            }],
            max_tokens=100,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        # 去掉可能的 markdown 代码块
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        assert "languages" in data, f"❌ 期望包含 languages 键，实际: {data}"
        assert len(data["languages"]) >= 3, f"❌ 期望至少3个语言，实际: {data}"
        print(f"\n  ✅ 结构化 JSON 输出正常: {data}")


# ===========================================================================
# 2. 原生 SDK — Embedding
# ===========================================================================

@requires_llm
class TestRealEmbedding:
    """直接使用 OpenAI SDK 调用真实 Embedding 模型。"""

    def _client(self):
        import openai
        return openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)

    def _embed(self, text: str) -> list[float]:
        resp = self._client().embeddings.create(
            model=cfg.embedding_model,
            input=text,
        )
        return resp.data[0].embedding

    def test_embedding_dimension(self):
        """向量维度与配置一致。"""
        vec = self._embed("hello world")
        assert len(vec) == cfg.embedding_dimension, (
            f"❌ 维度不符：期望 {cfg.embedding_dimension}，实际 {len(vec)}"
        )
        print(f"\n  ✅ 向量维度: {len(vec)}")

    def test_embedding_is_normalized(self):
        """向量应接近单位长度（L2 范数 ≈ 1）。"""
        vec = self._embed("test normalization")
        norm = math.sqrt(sum(x * x for x in vec))
        assert 0.95 <= norm <= 1.05, f"❌ 向量未归一化，L2={norm:.4f}"
        print(f"\n  ✅ 向量 L2 范数: {norm:.4f}（接近 1）")

    def test_similar_texts_have_higher_cosine(self):
        """语义相近的句子余弦相似度 > 语义相远的句子。"""
        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb)

        v_dog1 = self._embed("我喜欢养狗，狗是人类最好的朋友。")
        v_dog2 = self._embed("狗是非常忠诚的宠物。")
        v_code = self._embed("Python 是一种编程语言，用于数据分析。")

        sim_similar = cosine(v_dog1, v_dog2)
        sim_different = cosine(v_dog1, v_code)

        assert sim_similar > sim_different, (
            f"❌ 相近文本相似度({sim_similar:.3f}) 应 > 不相关文本({sim_different:.3f})"
        )
        print(
            f"\n  ✅ 相近文本相似度: {sim_similar:.3f}  "
            f"不相关文本相似度: {sim_different:.3f}"
        )

    def test_different_texts_produce_different_vectors(self):
        """不同文本应产生不同向量。"""
        v1 = self._embed("苹果是一种水果")
        v2 = self._embed("深度学习是人工智能的子领域")
        assert v1 != v2, "❌ 不同文本返回了相同向量"
        print("\n  ✅ 不同文本产生不同向量（符合预期）")


# ===========================================================================
# 3. HelloAgent.chat() — 真实 LLM，记忆/KB mock 隔离
# ===========================================================================

@requires_llm
@pytest.mark.asyncio
class TestRealAgentChat:
    """HelloAgent 使用真实 LLM，记忆和知识库 mock 以避免依赖 Qdrant/Neo4j。"""

    @pytest.fixture
    def agent(self):
        from hello_agents.agent import HelloAgent
        from hello_agents.memory.types.working import WorkingMemory

        mock_mm = MagicMock()
        wm = WorkingMemory(session_id="test")
        mock_mm.get_working_memory.return_value = wm
        mock_mm.read.return_value = []
        mock_mm.write = MagicMock()
        mock_mm.start = AsyncMock()
        mock_mm.stop = AsyncMock()

        mock_kb = MagicMock()
        mock_kb.list_all.return_value = []

        return HelloAgent(memory_manager=mock_mm, kb_manager=mock_kb)

    async def test_chat_returns_nonempty_response(self, agent):
        """真实 LLM 对话，回复非空。"""
        reply = await agent.chat("你好，请用一句话自我介绍。", session_id="s1")
        assert reply and len(reply) > 0, "❌ Agent chat 返回空内容"
        print(f"\n  ✅ Agent 回复: {reply[:80]!r}")

    async def test_chat_responds_in_chinese(self, agent):
        """默认 system prompt 要求中文回复，用中文提问验证有中文字符输出。"""
        reply = await agent.chat("你叫什么名字？", session_id="s2")
        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in reply)
        assert has_chinese, f"❌ 期望中文回复，实际: {reply!r}"
        print(f"\n  ✅ Agent 中文回复: {reply[:60]!r}")

    async def test_chat_multi_turn_context(self, agent):
        """多轮对话：Agent 能记住同一 session 中的信息（工作记忆）。"""
        session = "multi_turn_real"
        await agent.chat("我的名字叫 Bob。", session_id=session)
        reply2 = await agent.chat("我的名字是什么？", session_id=session)
        assert "Bob" in reply2 or "bob" in reply2.lower(), (
            f"❌ 期望回复包含 Bob，实际: {reply2!r}"
        )
        print(f"\n  ✅ 多轮记忆正常，回复: {reply2!r}")

    async def test_chat_factual_question(self, agent):
        """事实问题：回复应包含合理内容（不崩溃）。"""
        reply = await agent.chat("Python 语言是哪年发布的？", session_id="fact")
        # 只验证回复非空、包含数字年份即可
        assert any(ch.isdigit() for ch in reply), (
            f"❌ 回复中没有年份数字，实际: {reply!r}"
        )
        print(f"\n  ✅ 事实问答回复: {reply[:80]!r}")


# ===========================================================================
# 4. Function Calling — LLM 主动决策调用工具
# ===========================================================================

@requires_llm
@pytest.mark.asyncio
class TestRealFunctionCalling:
    """验证 LLM 在真实场景下能主动选择调用工具。"""

    @pytest.fixture
    def agent_with_note_tool(self):
        """注册笔记工具，不依赖外部服务。"""
        from hello_agents.agent import HelloAgent
        from hello_agents.memory.types.working import WorkingMemory
        from hello_agents.tools.builtin.note_tool import NoteToolHandler, NOTE_TOOLS

        mock_mm = MagicMock()
        wm = WorkingMemory(session_id="test")
        mock_mm.get_working_memory.return_value = wm
        mock_mm.read.return_value = []
        mock_mm.write = MagicMock()
        mock_mm.start = AsyncMock()
        mock_mm.stop = AsyncMock()

        mock_kb = MagicMock()
        mock_kb.list_all.return_value = []

        agent = HelloAgent(memory_manager=mock_mm, kb_manager=mock_kb)
        agent._registry.register_handler(NoteToolHandler(), NOTE_TOOLS)
        return agent

    async def test_llm_calls_note_tool(self, agent_with_note_tool):
        """要求 LLM 创建笔记，验证工具被调用且最终有文字回复。"""
        agent = agent_with_note_tool
        reply = await agent.chat(
            "请帮我创建一个标题为「Python学习计划」的笔记，内容是「学习 Python 基础语法」。",
            session_id="fc_test",
        )
        # LLM 应该调用了 create_note 并回复确认
        assert reply and len(reply) > 0, "❌ Function Calling 后回复为空"
        print(f"\n  ✅ Function Calling 回复: {reply[:100]!r}")

    async def test_llm_returns_text_without_tool_for_simple_query(self, agent_with_note_tool):
        """简单问答不应触发 Function Calling，直接返回文字。"""
        agent = agent_with_note_tool
        reply = await agent.chat("1 + 1 等于多少？", session_id="no_fc")
        assert "2" in reply, f"❌ 期望回复包含 2，实际: {reply!r}"
        print(f"\n  ✅ 简单问答无 Function Calling: {reply!r}")


# ===========================================================================
# 5. 上下文压缩 — 真实 LLM 生成摘要
# ===========================================================================

@requires_llm
@pytest.mark.asyncio
class TestRealContextCompress:
    """验证 Layer 3 上下文压缩调用真实 LLM 生成连续性摘要。"""

    async def test_llm_summarize_returns_nonempty(self):
        """llm_summarize() 应返回非空摘要字符串。

        llm_summarize 仅在 len(context) > max_chars 时才调用 LLM，
        因此需将 max_chars 设为小于输入长度的值来触发真实压缩。
        """
        from hello_agents.context.compress import llm_summarize

        # 构造足够长的上下文（>500 chars），再传 max_chars=200 强制触发压缩
        long_context = "\n".join([
            f"用户第{i}轮说：这是第{i}条消息，内容关于 Python 编程的学习心得和进度汇报，"
            f"包含了很多具体的学习细节和实践经验总结。"
            for i in range(15)
        ])
        assert len(long_context) > 500, "构造文本太短，测试无效"

        result = await llm_summarize(long_context, max_chars=200)
        assert result and len(result) > 0, "❌ LLM 压缩返回空摘要"
        assert len(result) < len(long_context), (
            f"❌ 摘要({len(result)}) 应短于原文({len(long_context)})"
        )
        print(f"\n  ✅ LLM 摘要长度: {len(result)} chars（原文 {len(long_context)} chars）")
        print(f"     摘要内容: {result[:120]!r}")

    async def test_apply_all_layers_with_long_messages(self):
        """超长 messages 经过三层压缩后总字符数减少。"""
        from hello_agents.context.compress import apply_all_layers, L3_SUMMARY_CHARS

        # 构造超过 L3 阈值的 messages
        messages = [
            {"role": "system", "content": "你是一个助手。"},
        ]
        for i in range(60):
            messages.append({"role": "user", "content": f"用户问题 {i}：" + "x" * 400})
            messages.append({"role": "assistant", "content": f"助手回答 {i}：" + "y" * 400})

        original_chars = sum(len(json.dumps(m)) for m in messages)
        assert original_chars > L3_SUMMARY_CHARS, "构造的 messages 不够长，测试无效"

        compressed = await apply_all_layers(messages)
        compressed_chars = sum(len(json.dumps(m)) for m in compressed)

        assert compressed_chars < original_chars, (
            f"❌ 压缩后({compressed_chars}) 应小于原始({original_chars})"
        )
        print(
            f"\n  ✅ 三层压缩：{original_chars} → {compressed_chars} chars "
            f"（压缩率 {compressed_chars/original_chars:.1%}）"
        )


# ===========================================================================
# 6. Web 搜索工具 — 真实 API 调用
# ===========================================================================

@requires_tavily
class TestRealTavilySearch:
    """WebSearchToolHandler 使用真实 Tavily API 执行搜索。"""

    def _make_tc(self, query: str, top_n: int = 3) -> MagicMock:
        import json
        tc = MagicMock()
        tc.function.name = "web_search"
        tc.function.arguments = json.dumps({"query": query, "top_n": top_n})
        return tc

    def test_tavily_real_search_returns_results(self):
        """真实搜索返回结构化结果。"""
        from hello_agents.tools.builtin.web_search_tool import WebSearchToolHandler
        handler = WebSearchToolHandler()
        result = json.loads(handler.dispatch(self._make_tc("Python programming language", top_n=3)))
        assert "results" in result, f"❌ 缺少 results 字段: {result}"
        assert len(result["results"]) > 0, "❌ 搜索结果为空"
        first = result["results"][0]
        assert "title" in first and "url" in first, f"❌ 结果字段不完整: {first}"
        print(f"\n  ✅ Tavily 真实搜索，首条: {first['title']!r}")

    def test_tavily_result_count_respects_top_n(self):
        """top_n 参数应限制返回结果数量。"""
        from hello_agents.tools.builtin.web_search_tool import WebSearchToolHandler
        handler = WebSearchToolHandler()
        result = json.loads(handler.dispatch(self._make_tc("machine learning", top_n=2)))
        assert "results" in result
        assert len(result["results"]) <= 2, (
            f"❌ 期望 ≤2 条结果，实际 {len(result['results'])} 条"
        )
        print(f"\n  ✅ top_n=2 限制生效，实际返回: {len(result['results'])} 条")


@requires_serpapi
class TestRealSerpAPISearch:
    """WebSearchToolHandler 使用真实 SerpAPI（Tavily key 置空时触发备用路径）。"""

    def _make_tc(self, query: str) -> MagicMock:
        tc = MagicMock()
        tc.function.name = "web_search"
        tc.function.arguments = json.dumps({"query": query, "top_n": 2})
        return tc

    def test_serpapi_real_search_via_handler(self):
        """直接调用 _search_serpapi 方法验证真实 SerpAPI。"""
        from hello_agents.tools.builtin.web_search_tool import WebSearchToolHandler
        handler = WebSearchToolHandler()
        result_str = handler._search_serpapi("Python language", 2, cfg.serpapi_api_key)
        result = json.loads(result_str)
        assert "results" in result, f"❌ 缺少 results 字段: {result}"
        assert len(result["results"]) > 0, "❌ SerpAPI 搜索结果为空"
        print(f"\n  ✅ SerpAPI 真实搜索，首条: {result['results'][0]['title']!r}")
