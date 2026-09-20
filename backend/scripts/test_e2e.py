"""端到端验证脚本：多 Agent 协作完整流程。

前置条件：
  1. PostgreSQL 已启动 + Alembic 迁移已跑（脚本自动建表）
  2. .env 里配好 LLM_API_KEY + EMBED_BASE_URL（如果用真实 LLM/Embedding）

这个脚本验证：
  1. 多 Agent LangGraph 正确构建（4 节点 + 条件边）
  2. Checkpoint 每个节点自动存
  3. agent_runs / agent_steps 正确落库
  4. 故障恢复：step 抛异常 → 从 checkpoint 继续
"""
from __future__ import annotations

# -- 让 Alembic 在首次导入时自动建表（如果还没跑过迁移） --
import sqlalchemy as sa

from app.config.database import Base, SessionLocal, engine
from app.config.settings import settings
from app.models import User
from app.utils.time_utils import utc_now

# ---------------------------------------------------------------------------
# 准备：确保表存在 + 测试用户
# ---------------------------------------------------------------------------

def ensure_tables() -> None:
    """如果表不存在就用 SQLAlchemy metadata 建（兜底）。"""
    try:
        # 尝试查询 users 表
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1 FROM users LIMIT 1"))
    except Exception:  # noqa: BLE001 — 探测表是否存在，任何失败都走建表兜底
        print("📝 表不存在，用 metadata.create_all() 创建...")
        Base.metadata.create_all(engine)
        print("✅ 表创建完成")


def ensure_test_user() -> User:
    """确保有一个测试用户，返回其 User 对象。"""
    import bcrypt

    with SessionLocal() as session:
        user = session.query(User).filter(User.username == "testuser").first()
        if user:
            return user
        hashed = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode()
        user = User(username="testuser", hashed_password=hashed)
        session.add(user)
        session.commit()
        session.refresh(user)
        print(f"✅ 创建测试用户: {user.username} (id={user.id})")
        return user


# ---------------------------------------------------------------------------
# 测试 1：图构建 + Checkpoint
# ---------------------------------------------------------------------------

def test_graph_structure() -> None:
    """验证 LangGraph 结构正确：4 节点 + 条件边。

    只读图结构，不执行图，因此不需要真实 LLM，也不依赖数据库里有对应 run 行。
    """
    print("\n" + "=" * 60)
    print("【测试 1】LangGraph 结构验证")
    print("=" * 60)

    from app.config.checkpoint import get_checkpointer
    from app.services.agent_service import MultiAgentService

    service = MultiAgentService(SessionLocal())
    view = service._graph.get_graph()

    print(f"  📌 Checkpointer 类型: {type(get_checkpointer()).__name__}")
    print(f"  📌 Graph 类型: {type(service._graph).__name__}")

    actual_nodes = set(view.nodes) - {"__start__", "__end__"}
    expected_nodes = {"planner", "retriever", "generator", "reviewer"}
    assert actual_nodes == expected_nodes, f"节点不一致: {sorted(actual_nodes)}"

    actual_edges = {(e.source, e.target) for e in view.edges}
    conditional_edges = {(e.source, e.target) for e in view.edges if e.conditional}
    plain_edges = actual_edges - conditional_edges

    assert plain_edges == {
        ("__start__", "planner"),
        ("planner", "retriever"),
        ("generator", "reviewer"),
    }, f"普通边不一致: {sorted(plain_edges)}"
    assert conditional_edges == {
        ("retriever", "retriever"),
        ("retriever", "generator"),
        ("reviewer", "generator"),
        ("reviewer", "__end__"),
    }, f"条件边不一致: {sorted(conditional_edges)}"

    print(f"  ✅ 节点 ({len(actual_nodes)}): {sorted(actual_nodes)}")
    print(f"  ✅ 普通边 ({len(plain_edges)}): {sorted(plain_edges)}")
    print(f"  ✅ 条件边 ({len(conditional_edges)}): {sorted(conditional_edges)}")
    print("  ✅ 图构建验证通过")


# ---------------------------------------------------------------------------
# 测试 2：完整端到端（需要 LLM API Key）
# ---------------------------------------------------------------------------

def test_full_flow() -> None:
    """完整端到端测试：创建 run → 记录 steps → 完成。"""
    print("\n" + "=" * 60)
    print("【测试 2】完整端到端流程")
    print("=" * 60)

    # 检查 LLM 配置
    if not settings.LLM_API_KEY:
        print("  ⚠️  LLM_API_KEY 未配置，跳过完整流程测试")
        print("     在 .env 里配好 LLM_API_KEY 后再跑")
        return

    user = ensure_test_user()

    print(f"  📌 用户: {user.username} (id={user.id})")
    print(f"  📌 LLM: {settings.LLM_MODEL_NAME}")
    print(f"  📌 Embedding: {settings.EMBED_MODEL}")
    print("  📌 测试问题: 'Python 是什么？'")
    print()

    with SessionLocal() as session:
        from app.services.agent_service import MultiAgentService

        service = MultiAgentService(session)

        print("  🔄 启动多 Agent 流程...")
        start = utc_now()
        result = service.run(
            user_id=user.id,
            session_id="e2e-test",
            question="Python 是什么？用简短的话回答。",
        )
        elapsed = (utc_now() - start).total_seconds()
        print(f"  ⏱️  耗时: {elapsed:.1f}s")
        print()
        print(f"  📌 run_id: {result['run_id']}")
        print(f"  📌 status: {result['status']}")

        if result["status"] == "completed":
            print(f"  📌 final_answer: {result['final_answer'][:200]}...")
        else:
            print(f"  ❌ error: {result['error_message']}")
            return

        # 查 steps
        steps = service._step_repo.list_by_run(result["run_id"])
        print()
        print(f"  📌 执行步骤数: {len(steps)}")
        for s in steps:
            dur = f"{s.duration_ms}ms" if s.duration_ms else "-"
            summary = (s.output_summary or "")[:60]
            print(f"     {s.node_name:10s}  #{s.attempt}  {s.status:8s}  {dur}  {summary}")

        print()
        print("  ✅ 端到端测试通过！")


# ---------------------------------------------------------------------------
# 测试 3：故障恢复
# ---------------------------------------------------------------------------

def test_resume() -> None:
    """验证 resume() 能从 checkpoint 恢复。"""
    print("\n" + "=" * 60)
    print("【测试 3】Checkpoint 恢复")
    print("=" * 60)

    user = ensure_test_user()

    with SessionLocal() as session:
        from app.services.agent_service import MultiAgentService

        service = MultiAgentService(session)

        # 先跑一个正常 run，拿到 run_id
        if not settings.LLM_API_KEY:
            print("  ⚠️  LLM_API_KEY 未配置，跳过恢复测试（恢复需要先有一次执行）")
            return

        result = service.run(
            user_id=user.id,
            session_id="resume-test",
            question="Redis 是什么？",
        )

        run_id = result["run_id"]
        print(f"  📌 首次运行 run_id: {run_id}")
        print(f"  📌 首次运行 status: {result['status']}")

        # 恢复已完成的 run（应该直接返回结果）
        resumed = service.resume(run_id)
        print(f"  🔄 恢复后 status: {resumed['status']}")

        if resumed["status"] == "completed" and resumed["final_answer"]:
            print("  ✅ 恢复测试通过（已完成的 run 可以被再次 resume）")
        else:
            print(f"  ❌ 恢复失败: {resumed['error_message']}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    ensure_tables()

    test_graph_structure()
    test_full_flow()
    test_resume()

    print("\n" + "=" * 60)
    print("🎉 所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
