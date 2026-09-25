# 文档导航

本目录收录 agent-orchestrator 的设计与开发文档，按"需求 → 数据库 → 接口 → 架构 → 前端"流程组织。

| 文档 | 内容 |
| --- | --- |
| [requirements.md](./requirements.md) | 需求文档：产品定位、目标用户、用户故事、功能清单、非功能性需求、范围边界 |
| [architecture.md](./architecture.md) | 架构与分层规范：五层调用、Agent 编排设计（双模式 / 护栏 / HITL）、目录结构、调用链、编码规范 |
| [database-design.md](./database-design.md) | 数据库表设计：ER 关系、七张表字段/约束/索引、pgvector 向量检索与级联删除 |
| [api-reference.md](./api-reference.md) | 接口一览（总表）：按模块分类的全部接口速查表 |
| [api-spec.md](./api-spec.md) | API 接口规范：通用约定（鉴权 / 统一响应 / 错误）、全部接口请求响应、SSE 事件格式、状态码 |
| [frontend-design.md](./frontend-design.md) | 前端 UI 设计：页面路由、核心交互、SSE 消费、时间线与人工裁决、目录建议、对接要点 |
| [getting-started.md](./getting-started.md) | 环境准备与开发启动：Makefile 一键命令、配置分组、手动分步 |

> 说明：
> - `.Project_Help/` 是本项目的**技术知识库**（按主题讲解框架与实现原理），与本文档互补：本文档讲"项目本身是什么"，知识库讲"底层技术怎么运作"。
> - 生产部署（Dockerfile / nginx / CI）尚未就绪，见 `Problem/08`；就绪后补 `deployment.md`。

## 阅读顺序建议

1. 先看 `requirements.md` 了解要做什么；
2. 再看 `architecture.md` 理解分层与编排设计；
3. 联调 / 接前端时查 `api-spec.md` 与 `database-design.md`；
4. 前端开发阶段参考 `frontend-design.md`。
