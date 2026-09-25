"""动态编排 —— 由模型决定节点流转的多 Agent 图。

与确定性编排的区别只有一处：谁决定下一步。

确定性编排把路径写死在图的边上，planner 之后必然是 retriever，generator 之后
必然是 reviewer。动态编排在中间加一个 supervisor 节点，每一步都由它看当前进展
决定下一个该由谁执行，工人执行完再回到它。

代价是每一步多一次模型调用；收益是路径可以随任务形状变化，也为接入更多工具
留出位置：新增工具只要注册进工具表，由 supervisor 决定要不要调用。

护栏：
    模型决策不受约束，因此叠加六层保护 —— 步数上限、目标白名单校验、前置状态
    校验、原地打转检测、工具调用次数上限、重试次数上限。任一层触发都退回规则
    路径，保证图无论模型输出什么都一定收敛。
"""

from __future__ import annotations

import ast
import json
import logging
import operator
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.config.llm_client import get_llm
from app.config.settings import settings

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from app.services.agent_service import AgentState, MultiAgentService

logger = logging.getLogger(__name__)

# supervisor 允许派发的目标，越界值一律回退规则路由
VALID_TARGETS: frozenset[str] = frozenset(
    {"planner", "retriever", "generator", "reviewer", "tool"}
)

# 模型有时把 JSON 包在代码块围栏里，先剥掉再解析
_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 工具生态
# ---------------------------------------------------------------------------

_BIN_OPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ExpressionError(ValueError):
    """表达式不合法，或包含白名单之外的运算。"""


def _eval_expr(node: ast.AST) -> float:
    """递归求值算术表达式，只放行数字常量与白名单运算符。

    表达式来自模型输出，直接 eval 会开出任意代码执行的口子，
    因此这里走 AST 白名单求值，遇到任何其他语法一律拒绝。
    """

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ExpressionError("只支持数字常量")

    if isinstance(node, ast.BinOp):
        handler = _BIN_OPS.get(type(node.op))
        if handler is None:
            raise ExpressionError(f"不支持的运算符 {type(node.op).__name__}")
        return handler(_eval_expr(node.left), _eval_expr(node.right))

    if isinstance(node, ast.UnaryOp):
        unary = _UNARY_OPS.get(type(node.op))
        if unary is None:
            raise ExpressionError("不支持的一元运算")
        return unary(_eval_expr(node.operand))

    raise ExpressionError("表达式包含未允许的语法")


def tool_calculate(arguments: dict[str, Any], state: AgentState) -> str:
    """按算术表达式求值。只接受数字与加减乘除取模乘方。"""

    expression = str(arguments.get("expression", "")).strip()
    if not expression:
        return "calculate 缺少 expression 参数"

    try:
        value = _eval_expr(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ExpressionError, ZeroDivisionError, OverflowError) as exc:
        return f"计算失败: {exc}"
    return f"{expression} = {value:g}"


def tool_context_stats(arguments: dict[str, Any], state: AgentState) -> str:
    """统计当前已检索到的上下文片段，供模型判断信息是否已经够用。"""

    docs = state.get("context_docs", [])
    if not docs:
        return "当前没有已检索的上下文片段"

    scores = [float(doc.get("score") or 0.0) for doc in docs]
    documents = {str(doc.get("document_id")) for doc in docs}
    return (
        f"已检索片段 {len(docs)} 个，来自 {len(documents)} 篇文档，"
        f"最高分 {max(scores):.3f}，最低分 {min(scores):.3f}"
    )


# 工具表：新增工具只要实现同样的签名并登记在这里，supervisor 就能调它
TOOL_REGISTRY: dict[str, Callable[[dict[str, Any], AgentState], str]] = {
    "calculate": tool_calculate,
    "context_stats": tool_context_stats,
}


# ---------------------------------------------------------------------------
# supervisor 决策
# ---------------------------------------------------------------------------

SUPERVISOR_PROMPT = """你是多 Agent 协作流程的调度员。根据下面的阶段状态，决定下一步交给哪个角色。

可选角色：
- planner    把用户问题拆成可以独立检索的子问题
- retriever  检索文档片段，补齐上下文
- generator  基于已有上下文写出回答草稿
- reviewer   审核草稿质量，不合格时给出改进建议
- tool       调用工具，例如数值计算或查看上下文统计
- finish     流程结束，输出最终回答

判断顺序，从上往下检查，命中第一条就选它：
1. 问题拆解 的状态是「未开始」的时候选 planner
2. 文档检索 的状态是「进行中」的时候选 retriever
3. 回答草稿 的状态是「未开始」，且用户问题需要数值计算，选 tool
4. 回答草稿 的状态是「未开始」的时候选 generator
5. 质量审核 的状态是「未开始」的时候选 reviewer
6. 质量审核 的状态是「不通过」的时候选 generator，带上改进建议重写
7. 质量审核 的状态是「已通过」的时候选 finish

阶段状态：
{progress}

用户问题：{question}

只返回一个 JSON 对象，不要输出其他内容：
{{"next": "角色名", "reason": "一句话理由"}}"""


def _progress_digest(state: AgentState) -> str:
    """把状态压成阶段状态清单，供 supervisor 判断进展。

    每个阶段只报「未开始 / 进行中 / 已完成」加必要数字，与 SUPERVISOR_PROMPT
    的判断条件用词一致。早期版本报裸数字（子问题 2 个、已检索 0 个），
    弱模型会把两个数字揉在一起，从「已检索 0 个」推出「还没拆过子问题」，
    于是反复派回 planner；改成阶段状态后同一批场景 15 次判定全对。
    """

    sub_tasks = state.get("sub_tasks", [])
    total = len(sub_tasks)
    retrieved = state.get("current_task_index", 0)
    docs = len(state.get("context_docs", []))

    if total == 0:
        plan = "未开始"
        retrieve = "未开始"
    else:
        plan = f"已完成，共 {total} 个子问题"
        if retrieved < total:
            retrieve = f"进行中，{total} 个子问题已检索 {retrieved} 个"
        else:
            retrieve = f"已完成，{total} 个子问题全部检索完，共 {docs} 条片段"

    if state.get("final_answer"):
        review = "已通过"
    elif state.get("review_feedback"):
        review = "不通过"
    else:
        review = "未开始"

    return "\n".join(
        [
            f"- 问题拆解: {plan}",
            f"- 文档检索: {retrieve}",
            f"- 回答草稿: {'已生成' if state.get('draft_answer') else '未开始'}",
            f"- 质量审核: {review}",
            f"- 工具调用: 已调用 {len(state.get('tool_trace', []))} 次",
            f"- 重试次数: {state.get('retry_count', 0)} / {state.get('max_retry', 3)}",
            f"- 已执行步数: {state.get('step_count', 0)} / {settings.AGENT_MAX_STEPS}",
        ]
    )


def _progress_key(state: AgentState) -> str:
    """实质进展的指纹，用于识别原地打转。

    刻意不含步数：步数每轮都加一，算进来指纹永不重复，打转就识别不出来。
    工具调用也计入进展，否则连续调工具会被误判成打转。
    """

    return "|".join(
        [
            str(len(state.get("sub_tasks", []))),
            str(state.get("current_task_index", 0)),
            str(len(state.get("context_docs", []))),
            str(len(state.get("tool_trace", []))),
            "1" if state.get("draft_answer") else "0",
            "1" if state.get("final_answer") else "0",
            (state.get("review_feedback") or "")[:40],
            str(state.get("retry_count", 0)),
        ]
    )


def _prerequisites_met(target: str, state: AgentState) -> bool:
    """判断目标节点的前置状态是否已具备。

    模型可以直接点名任意工人节点，但每个节点本体都假设前置节点已经把共享状态
    写好了：retriever 读 sub_tasks 与 current_task_index，generator 与 reviewer
    读 context_docs，reviewer 还需要 draft_answer。跳过前置节点直接点名下游节点，
    节点就会读到不存在的键而抛 KeyError，整轮运行以 failed 收尾。因此「前置状态
    是否具备」必须与目标名一道纳入护栏，不满足时退回规则路径，而不是让节点崩掉。
    """

    if target == "retriever":
        sub_tasks = state.get("sub_tasks", [])
        return bool(sub_tasks) and state.get("current_task_index", 0) < len(sub_tasks)
    if target == "generator":
        return "context_docs" in state
    if target == "reviewer":
        return "draft_answer" in state
    return True


def rule_based_route(state: AgentState) -> str:
    """规则兜底路径，与确定性编排的边保持同样的顺序。

    模型决策不可用、给出非法目标或触发护栏时使用，保证流程始终能往下走。
    """

    if state.get("final_answer"):
        return END
    if not state.get("sub_tasks"):
        return "planner"
    if state.get("current_task_index", 0) < len(state.get("sub_tasks", [])):
        return "retriever"
    if not state.get("draft_answer"):
        return "generator"
    if state.get("review_feedback"):
        if state.get("retry_count", 0) >= state.get("max_retry", 3):
            return END
        return "generator"
    return "reviewer"


TOOL_PROMPT = """你是工具调用规划器。判断下面的问题是否需要先调用工具。

可用工具：
- calculate      计算纯算术表达式，参数为 {{"expression": "120 * 0.85"}}
- context_stats  查看已检索上下文片段的数量与分数分布，无参数

只返回一个 JSON 对象：
{{"tool": "工具名或 null", "arguments": {{}}, "reason": "一句话理由"}}

当前进展：
{progress}

用户问题：{question}"""


def _plan_tool_call(state: AgentState) -> dict[str, Any] | None:
    """让模型决定是否调用工具、调用哪个、传什么参数。"""

    prompt = ChatPromptTemplate.from_template(TOOL_PROMPT)
    chain: Any = prompt | get_llm() | StrOutputParser()

    # 工具规划失败只影响这一次工具调用，不应中断整轮问答
    try:
        raw = chain.invoke(
            {"question": state["question"], "progress": _progress_digest(state)}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool planning failed: %s", exc)
        return None

    try:
        parsed = json.loads(_FENCE.sub("", raw).strip())
    except json.JSONDecodeError:
        logger.warning("tool planning returned non-json: %r", raw[:120])
        return None

    name = parsed.get("tool")
    if not isinstance(name, str) or name not in TOOL_REGISTRY:
        return None

    arguments = parsed.get("arguments")
    return {
        "tool": name,
        "arguments": arguments if isinstance(arguments, dict) else {},
        "reason": str(parsed.get("reason", ""))[:120],
    }


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------


class _WorkerNode:
    """工人节点包装器：节点本体执行完，用 Command 把控制权交回 supervisor。

    确定性编排里节点之间靠边相连，节点只要返回状态增量即可；动态编排里节点
    之间不连边，因此节点必须显式声明下一个执行者是谁，这一步由 Command 完成。
    包装器只补上这层跳转，节点实现本身完全复用。
    """

    def __init__(self, node_fn: Callable[[AgentState], AgentState]) -> None:
        self._node_fn = node_fn

    def __call__(self, state: AgentState) -> Command:
        return Command(goto="supervisor", update=self._node_fn(state))


def build_dynamic_graph(
    service: MultiAgentService,
    checkpointer: BaseCheckpointSaver | None,
) -> CompiledStateGraph:
    """构建 supervisor 动态路由图。

    supervisor 位于中心，四个工人节点与工具节点都从它出发、执行完回到它。
    节点本体直接复用确定性编排里的实现，这里只负责用 Command 重新连线。
    """
    # StateGraph 构造需要 AgentState 的真实对象，注解用的是 TYPE_CHECKING 版本
    from app.services.agent_service import AgentState as _AgentState

    def decide_next(state: AgentState) -> tuple[str, str]:
        """让模型决定下一个节点，失败时回退规则路径。"""

        prompt = ChatPromptTemplate.from_template(SUPERVISOR_PROMPT)
        chain: Any = prompt | get_llm() | StrOutputParser()

        try:
            raw = chain.invoke(
                {"progress": _progress_digest(state), "question": state["question"]}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("supervisor decision failed: %s", exc)
            return rule_based_route(state), "模型调用失败，回退规则路由"

        try:
            parsed = json.loads(_FENCE.sub("", raw).strip())
        except json.JSONDecodeError:
            logger.warning("supervisor returned non-json: %r", raw[:120])
            return rule_based_route(state), "输出非 JSON，回退规则路由"

        target = str(parsed.get("next", "")).strip()
        if target == "finish":
            target = END
        return target, str(parsed.get("reason", ""))[:120]

    def supervisor(state: AgentState) -> Command:
        """每一步由模型决定去向，并在这里统一做护栏校验。"""

        run_id = state["run_id"]
        step_count = int(state.get("step_count", 0))
        step_id = service._record_step_start(
            run_id, "supervisor", f"第 {step_count + 1} 步"
        )

        # 护栏一：步数到顶直接收尾，避免模型把流程拖成循环
        if step_count >= settings.AGENT_MAX_STEPS:
            service._record_step_done(step_id, "success", "达到最大步数，收尾")
            return Command(goto=END, update={"step_count": step_count + 1})

        target, reason = decide_next(state)

        # 护栏二：目标必须在白名单内，越界时退回规则路径
        if target not in VALID_TARGETS and target != END:
            logger.warning("supervisor 给出非法目标 %r，回退规则路由", target)
            target = rule_based_route(state)
            reason = "非法目标，回退规则路由"

        # 护栏三：目标节点的前置状态必须已就绪，否则节点会读到缺失的状态键
        if target != END and not _prerequisites_met(target, state):
            logger.warning("supervisor 派发 %r 时前置状态未就绪，回退规则路由", target)
            target = rule_based_route(state)
            reason = "前置状态未就绪，回退规则路由"

        # 护栏四：连续两次选同一目标且实质进展没变，判定为原地打转
        progress_key = _progress_key(state)
        if target == state.get("last_target") and progress_key == state.get(
            "last_progress_key"
        ):
            logger.warning("supervisor 重复选择 %r 且无进展，回退规则路由", target)
            target = rule_based_route(state)
            reason = "重复选择且无进展，回退规则路由"

        # 护栏五：工具调用次数封顶，避免模型反复调工具空刷步数
        tool_calls = len(state.get("tool_trace", []))
        if target == "tool" and tool_calls >= settings.AGENT_MAX_TOOL_CALLS:
            logger.warning("工具调用已达上限 %d 次，回退规则路由", tool_calls)
            target = rule_based_route(state)
            reason = "工具调用已达上限，回退规则路由"

        # 护栏六：重试次数已满时不允许再回到 generator 重写
        if target == "generator" and state.get("retry_count", 0) >= state.get(
            "max_retry", 3
        ):
            target = END
            reason = "重试已达上限，收尾"

        service._record_step_done(step_id, "success", f"next={target} :: {reason}")
        return Command(
            goto=target,
            update={
                "step_count": step_count + 1,
                "last_target": target,
                "last_progress_key": progress_key,
            },
        )

    def tool_node(state: AgentState) -> Command:
        """工具节点：由模型选出工具与参数，执行结果记进工具轨迹。"""

        run_id = state["run_id"]
        step_id = service._record_step_start(
            run_id, "tool", f"question: {str(state['question'])[:120]}"
        )

        try:
            plan = _plan_tool_call(state)
            if plan is None:
                service._record_step_done(step_id, "success", "无需调用工具")
                return Command(goto="supervisor", update={})

            result = TOOL_REGISTRY[plan["tool"]](plan["arguments"], state)
            trace = [*state.get("tool_trace", []), {**plan, "result": result}]
            service._record_step_done(
                step_id, "success", f"{plan['tool']} -> {result[:120]}"
            )
            return Command(goto="supervisor", update={"tool_trace": trace})

        # 记录节点失败后向上抛出，由上层统一落库为 failed
        except Exception as e:
            service._record_step_failed(run_id, "tool", str(e))
            raise

    graph = StateGraph(_AgentState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("planner", _WorkerNode(service._planner_node))
    graph.add_node("retriever", _WorkerNode(service._retriever_node))
    graph.add_node("generator", _WorkerNode(service._generator_node))
    graph.add_node("reviewer", _WorkerNode(service._reviewer_node))
    graph.add_node("tool", tool_node)

    # 动态模式下节点之间不连边，全部由 supervisor 的 Command 决定去向
    graph.add_edge(START, "supervisor")

    return graph.compile(checkpointer=checkpointer)
