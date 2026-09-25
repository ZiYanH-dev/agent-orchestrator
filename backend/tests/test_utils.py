"""工具函数与配置对象的单元测试。

时间工具的契约是「所有写入数据库的时间都带时区」：数据库列声明为
DateTime(timezone=True)，读写两侧只要一侧是 naive，相减就会抛 TypeError。
as_utc 是这条契约的兜底，因此单独覆盖。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.config.settings import PROJECT_ROOT, Settings, settings
from app.utils.time_utils import as_utc, utc_now

# ---------------------------------------------------------------------------
# time_utils
# ---------------------------------------------------------------------------

def test_utc_now_is_timezone_aware_utc() -> None:
    """utc_now 必须返回带 UTC 时区的时间。"""

    now = utc_now()

    assert now.tzinfo is UTC
    assert now.utcoffset() == timedelta(0)


def test_as_utc_attaches_utc_to_naive_datetime() -> None:
    """naive 时间按 UTC 解释，墙上时间不变。"""

    naive = datetime(2026, 9, 22, 10, 30, 0)
    fixed = as_utc(naive)

    assert fixed.tzinfo is UTC
    assert (fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute) == (
        2026,
        9,
        22,
        10,
        30,
    )


def test_as_utc_keeps_aware_datetime_intact() -> None:
    """已带时区的时间原样返回，不做时区搬运。"""

    aware = datetime(2026, 9, 22, 10, 30, 0, tzinfo=UTC)

    assert as_utc(aware) is aware


def test_as_utc_preserves_non_utc_timezone() -> None:
    """非 UTC 的时区也要保留，否则会比实际时间偏移。"""

    tokyo = timezone(timedelta(hours=9))
    aware = datetime(2026, 9, 22, 10, 30, 0, tzinfo=tokyo)

    assert as_utc(aware) == aware
    assert as_utc(aware).tzinfo == tokyo


def test_aware_datetimes_can_be_subtracted() -> None:
    """回归：naive 与 aware 混用会抛 TypeError，as_utc 之后必须能相减。"""

    naive = datetime(2026, 9, 22, 10, 0, 0)
    delta = utc_now() - as_utc(naive)

    assert isinstance(delta, timedelta)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_database_url_assembled_from_parts() -> None:
    """DATABASE_URL 留空时按各分量拼出 psycopg 连接串。"""

    config = Settings(
        DATABASE_URL="",
        POSTGRES_USER="u",
        POSTGRES_PASSWORD="p",
        POSTGRES_HOST="h",
        POSTGRES_PORT=1234,
        POSTGRES_DB="d",
    )

    assert config.resolved_database_url == "postgresql+psycopg://u:p@h:1234/d"


def test_explicit_database_url_wins() -> None:
    """显式给出的连接串优先于分量拼装。"""

    config = Settings(DATABASE_URL="postgresql+psycopg://explicit@localhost/db")

    assert config.resolved_database_url == "postgresql+psycopg://explicit@localhost/db"


def test_redis_url_with_and_without_password() -> None:
    """有密码时插入 auth 段，无密码时不插入多余的 @。"""

    without = Settings(REDIS_URL="", REDIS_HOST="h", REDIS_PORT=6380, REDIS_DB=2, REDIS_PASSWORD="")
    with_password = Settings(
        REDIS_URL="", REDIS_HOST="h", REDIS_PORT=6379, REDIS_DB=0, REDIS_PASSWORD="secret"
    )

    assert without.resolved_redis_url == "redis://h:6380/2"
    assert with_password.resolved_redis_url == "redis://:secret@h:6379/0"


def test_cors_origins_list_strips_and_drops_blanks() -> None:
    """逗号分隔的跨域白名单要去空白、丢空项。"""

    config = Settings(CORS_ORIGINS="http://a:1 , http://b:2 ,, ")

    assert config.cors_origins_list == ["http://a:1", "http://b:2"]


def test_data_dir_path_is_anchored_to_backend() -> None:
    """数据目录锚定在 backend/ 下，不受进程工作目录影响。"""

    config = Settings(DATA_DIR="data")

    assert config.data_dir_path == PROJECT_ROOT / "data"
    assert config.data_dir_path.is_absolute()


def test_embedding_and_vector_dimensions_agree() -> None:
    """EMBED_DIMENSION 与 VECTOR_DIMENSION 必须相等。

    两者语义上是同一个值：前者描述 Embedding 服务输出多少维，后者决定
    chunks.embedding 列建多少维。若只改其中一个，写入向量时 PostgreSQL 会因
    维度不匹配拒绝插入，而报错点在入库那一步，排查成本高。这条断言把两者锁死。
    """

    assert settings.EMBED_DIMENSION == settings.VECTOR_DIMENSION


def test_agent_guardrail_settings_are_sane() -> None:
    """护栏参数必须为正，否则护栏一开始就处于触发状态。"""

    assert settings.AGENT_MAX_STEPS > 0
    assert settings.AGENT_MAX_TOOL_CALLS > 0
    assert settings.AGENT_ORCHESTRATION_MODE in {"deterministic", "dynamic"}
    assert settings.AGENT_CHECKPOINT_BACKEND in {"memory", "redis"}


def test_project_root_points_to_backend() -> None:
    """PROJECT_ROOT 应指向 backend 目录（其下存在 app 包）。"""

    assert (PROJECT_ROOT / "app").is_dir()
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
