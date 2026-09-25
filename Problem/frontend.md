# 前端问题（Frontend）

> 2026-09-22 审查发现。状态标签：[OPEN] 未修复 / [WIP] 部分修复 / [DONE] 已修复。
> 按原编号顺序排列；编号仅用于跨条目引用，不代表处理优先级。

---

## [OPEN] 09. 前端生产包单 chunk 超过 1 MB

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 未修复 |
| 影响层 | 前端 |
| 位置 | `frontend/src/main.ts`、`frontend/vite.config.js` |
| 首次发现 | 2026-09-22 |

### 现象

`pnpm build` 输出单个 JS chunk 体积 1,127 kB，gzip 后 372 kB。

Vite 打印 `(!) Some chunks are larger than 500 kB after minification` 告警。

### 根因

`main.ts` 里用 `app.use(ElementPlus)` 全量注册组件库。

全量注册会把 Element Plus 的所有组件及其样式一次性打进主 chunk，无法被 tree-shaking 裁掉。

`vite.config.js` 没有配置 `build.rollupOptions.output.manualChunks`，因此第三方库与业务代码同处一个 chunk。

### 证据

```bash
cd frontend && pnpm build
# dist/assets/index-3ENyv4c_.js   1,127.22 kB │ gzip: 372.20 kB
# dist/assets/index-CNzseHV1.css    372.48 kB │ gzip:  50.55 kB
# (!) Some chunks are larger than 500 kB after minification.
```

### 影响

首屏需要下载并解析 1.1 MB 的 JS，在移动网络或弱机型上首屏可见时间明显变长。

单 chunk 意味着任何一处业务代码改动都会让浏览器整体缓存失效，用户每次发版都要重新下载全部体积。

对本地开发没有影响，开发模式走按需编译。

### 建议改法

三条路径按收益从高到低排列。

1. 改为按需引入：用 `unplugin-vue-components` 配 `ElementPlusResolver` 自动按需注册，只打包实际用到的组件与样式。
2. 拆分 vendor chunk：在 `vite.config.js` 增加 `manualChunks`，把 `element-plus`、`vue`、`pinia`、`vue-router` 分到独立 chunk，利用浏览器缓存。
3. 路由级懒加载：把 `router/index.ts` 里的静态 `import` 换成 `() => import("@/views/XxxView.vue")`，让每个页面独立成 chunk。

第 2、3 条只改配置与路由写法，不动业务代码，可以先行。

第 1 条需要调整 `main.ts` 的注册方式，改动面稍大但收益最高。

### 验证方式

```bash
cd frontend && pnpm build
# 期望：无 chunk 体积告警，最大 chunk 显著小于 500 kB
```

### 备注

引入按需引入插件属于新增依赖，需要先确认是否走 pnpm 且是否使用国内镜像。

## [OPEN] 10. 前端开发服务器只监听 IPv6 回环地址

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 未修复 |
| 影响层 | 前端 |
| 位置 | `frontend/vite.config.js`（`server` 段） |
| 关联位置 | `.env`（`CORS_ORIGINS`） |
| 首次发现 | 2026-09-22 |

### 现象

前端开发服务器只监听 `[::1]:5872`。

访问 `http://localhost:5872` 返回 200，访问 `http://127.0.0.1:5872` 返回 HTTP 000，也就是连接不上。

### 根因

`vite.config.js` 只设了 `server.port`，没有设 `server.host`。

Vite 在未指定 `host` 时使用 `localhost`，而 macOS 上 `localhost` 优先解析为 IPv6 回环 `::1`，于是进程只绑定了 IPv6。

后端 uvicorn 用 `--host` 未指定，默认绑定 `127.0.0.1`，也就是只绑 IPv4，方向恰好相反。

### 证据

```bash
lsof -nP -iTCP:5872 -sTCP:LISTEN
# node  ...  TCP [::1]:5872 (LISTEN)      <- 只有 IPv6

curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5872/   # 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5872/   # 000
```

后端的绑定方向相反，但两种地址都能连上。

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
# python3.1 ... TCP 127.0.0.1:8765 (LISTEN)   <- 只有 IPv4

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/health   # 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8765/health   # 200
```

差异的原因是回退方向不对称：`localhost` 先解析到 `::1`，失败后可以回退到 IPv4；而字面量 `127.0.0.1` 只能走 IPv4，没有可回退的目标。

### 影响

用 `127.0.0.1:5872` 作为访问地址的脚本、浏览器书签、自动化测试都会失败。

这个差异难以从字面看出来，因为两个地址看起来等价，排查时会优先怀疑服务没起来。

`make start` 打印的访问入口用的是 `localhost`，所以按提示操作不受影响。

`CORS_ORIGINS` 同时列了 `http://127.0.0.1:5872` 与 `http://localhost:5872`，说明两种写法都被预期使用，但实际只有一种能连上。

### 建议改法

在 `frontend/vite.config.js` 的 `server` 段显式指定 `host: "127.0.0.1"`，与后端的绑定地址保持一致。

若希望局域网内其他设备也能访问，改为 `host: true`，同时把该地址加进 `CORS_ORIGINS`。

后端可选的对称做法是启动时用 `--host 0.0.0.0`，但那会扩大监听范围，需先确认是否符合预期。

### 验证方式

```bash
lsof -nP -iTCP:5872 -sTCP:LISTEN
# 期望：TCP 127.0.0.1:5872 (LISTEN)

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5872/   # 期望 200
```

### 备注

后端 `/health` 的探测地址同理：`scripts/http_e2e.py` 与 `verify_hitl_http.py` 都硬编码了 `127.0.0.1`，因此对后端不构成问题，只影响前端。

## [OPEN] 15.3 · 前端缺少四个规范目录

| 项 | 值 |
| --- | --- |
| 严重级别 | ⚪ P3 |
| 状态 | 未修复 |
| 影响层 | 规范一致性 |
| 位置 | `frontend/src/` |
| 首次发现 | 2026-09-22 |

### 现象

规范里列出了 `composables/`、`types/`、`utils/`、`assets/` 四个目录，实际都不存在。

### 现状对照

| 目录 | 当前状态 |
| --- | --- |
| `api/` | 存在 |
| `components/` | 存在 |
| `router/` | 存在 |
| `stores/` | 存在 |
| `views/` | 存在 |
| `composables/` | 缺失 |
| `types/` | 缺失 |
| `utils/` | 缺失 |
| `assets/` | 缺失 |

### 影响

目前没有跨文件复用的逻辑与类型，因此四个目录没有内容可放。

影响是「规范与代码不一致」：新成员按规范找 `types/` 会找不到，不知道类型应该放哪。

### 建议改法

两种处理都需要明确选一种。

1. 按需创建：在规范文档里注明这四个目录是「出现第一个使用者时创建」，不做空目录提交。
2. 预建目录：放 `.gitkeep` 占位，并把每个目录的职责写进 `README`。

当前状态是第三种：既没建目录，规范里也没写清楚，因此归为一致性问题。
