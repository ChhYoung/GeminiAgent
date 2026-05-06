"""
examples/team_solve.py — 动态 Agent 团队解决问题示例

支持任意类型的任务——技术任务、报告撰写、策略规划等均可。

用法（直接输入任务）：
    python examples/team_solve.py

用法（从文件读取任务描述）：
    python examples/team_solve.py --task-file path/to/task.md

用法（指定角色，跳过 LLM 分析）：
    python examples/team_solve.py --roles researcher analyst writer

用法（保存报告到文件）：
    python examples/team_solve.py --output report.md
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 确保可以从项目根目录运行
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("team_solve")

_DEFAULT_TASK = """
分析「远程工作对团队协作效率的影响」，并给出改善建议。
要求：
1. 梳理远程工作的主要优缺点及对协作的具体影响
2. 识别影响效率的关键因素（沟通、工具、文化等）
3. 提出可落地的改善方案，附优先级建议
4. 输出一份可直接呈送管理层的分析报告
""".strip()


async def main() -> None:
    parser = argparse.ArgumentParser(description="动态 Agent 团队解决问题")
    parser.add_argument("--task", type=str, help="任务描述（直接输入）")
    parser.add_argument("--task-file", type=str, help="任务描述文件路径")
    parser.add_argument(
        "--roles",
        nargs="+",
        choices=[
            # 通用角色
            "researcher", "analyst", "strategist", "writer", "critic", "editor",
            # 技术角色
            "architect", "coder", "tester", "reviewer", "documenter",
        ],
        help="直接指定角色（跳过 LLM 分析）",
    )
    parser.add_argument("--output", type=str, help="输出报告保存路径（.md）")
    args = parser.parse_args()

    # 确定任务描述
    if args.task_file:
        task_path = Path(args.task_file)
        if not task_path.exists():
            print(f"错误：文件不存在 {task_path}")
            sys.exit(1)
        task = task_path.read_text(encoding="utf-8").strip()
    elif args.task:
        task = args.task
    else:
        task = _DEFAULT_TASK

    print("=" * 60)
    print("动态 Agent 团队任务解决器")
    print("=" * 60)
    print(f"\n任务描述:\n{task}\n")

    # 懒加载（避免在 import 时触发配置读取）
    from hello_agents.teams.pipeline import TaskPipeline

    pipeline = TaskPipeline()

    if args.roles:
        print(f"指定角色: {' → '.join(args.roles)}\n")
    else:
        print("正在分析任务，自动确定所需角色...\n")

    result = await pipeline.solve(task, roles=args.roles)

    print("\n" + "=" * 60)
    print(f"执行完成！参与角色: {' → '.join(result.roles_used)}")
    print(f"总耗时: {result.total_elapsed_seconds:.1f}s")
    print("=" * 60)

    # 打印各角色产出摘要
    for role in result.roles_used:
        if role in result.outputs:
            out = result.outputs[role]
            preview = out.content[:200].replace("\n", " ")
            print(f"\n[{role}] ({out.elapsed_seconds:.1f}s): {preview}...")

    # 生成完整报告
    report = result.to_markdown()

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report, encoding="utf-8")
        print(f"\n完整报告已保存到: {output_path.resolve()}")
    else:
        print("\n" + "=" * 60)
        print("完整报告")
        print("=" * 60)
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
