# 文档上传与回收问题（Backend-Documents）

> 2026-09-22 审查发现。状态标签：[OPEN] 未修复 / [WIP] 部分修复 / [DONE] 已修复。
> 按原编号顺序排列；编号仅用于跨条目引用，不代表处理优先级。

---

## [OPEN] 16. 上传文件未做类型与编码校验，二进制文件触发 500

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟠 P1 |
| 状态 | 未修复 |
| 影响层 | Service 层（`DocumentService.ingest_file`） |
| 位置 | `backend/app/services/document_service.py:55` |
| 首次发现 | 2026-09-22 |

### 现象

上传任何非 UTF-8 编码的文件（PDF、Word、图片、压缩包），接口返回 HTTP 500 与通用错误文案。

前端的上传控件明确列出了 `.pdf`、`.doc`、`.docx` 三种格式，用户按提示操作必然踩中。

实测记录：

| 上传内容 | 扩展名 | HTTP 状态 | 响应体 |
| --- | --- | --- | --- |
| 纯文本 | `.txt` | 200 | `{"code":0,"message":"success","data":{...}}` |
| `%PDF-1.4` 加三个二进制字节 | `.pdf` | **500** | `{"code":1,"message":"服务器内部错误","data":null}` |

### 根因

`DocumentService.ingest_file` 把上传内容当纯文本读，没有判断文件类型。

```python
# backend/app/services/document_service.py
51    file_path: Path = save_upload_file(
52        file_bytes=file_bytes,
53        original_filename=filename,
54    )
55    content: str = file_path.read_text(encoding="utf-8")
```

`read_text` 固定用 UTF-8 解码，遇到不符合 UTF-8 字节序列的内容直接抛 `UnicodeDecodeError`。

上游没有任何拦截：

| 环节 | 是否校验 |
| --- | --- |
| 前端 `accept=".txt,.pdf,.md,.doc,.docx"` | 只是浏览器的选择器过滤，用户可以改成「所有文件」绕过 |
| 路由 `upload_document(file: UploadFile = File(...))` | 只校验有文件，不校验类型 |
| `save_upload_file` | 只取后缀名拼文件名，不校验后缀 |
| `DocumentService.ingest_file` | 无校验，直接按 UTF-8 解码 |

四层全部放行，错误在第 55 行才爆出来。

### 证据

后端日志里的完整堆栈（`.logs/backend.log`）：

```
File ".../app/api/routes/documents.py", line 26, in upload_document
    document: DocumentOut = service.ingest_file(
File ".../app/services/document_service.py", line 55, in ingest_file
    content: str = file_path.read_text(encoding="utf-8")
File ".../pathlib.py", line 1028, in read_text
    return f.read()
File "<frozen codecs>", line 322, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe2 in position 9: invalid continuation byte
```

复现命令：

```bash
BASE=http://127.0.0.1:8765/api/v1
TOKEN=<登录后拿到的 access_token>

printf '%%PDF-1.4\n\xe2\xe3\xcf\xd3\n' > /tmp/fake.pdf
curl -s -X POST "$BASE/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/fake.pdf" -w "\nHTTP %{http_code}\n"
```

### 影响

**用户侧**：提示语是「服务器内部错误」，用户不知道是文件格式问题，会反复重试同一个文件。

**运维侧**：这类错误会被 `ErrorHandlingMiddleware` 记为 500 并打出堆栈，合法的用户输入错误混进服务端异常日志，掩盖真正的故障。

**数据侧**：文件在 `read_text` 之前已经写入磁盘（第 51 行的 `save_upload_file` 先执行），而数据库里没有任何记录。详见下文「落盘文件从不回收」。

**安全侧**：后缀名完全不校验，`.php`、`.sh` 这类文件也会被原样落盘。当前数据目录不在 Web 根目录下，也没有执行入口，所以不构成直接风险；一旦后续增加「下载原文」接口，就变成任意文件下载与潜在的脚本执行。

### 建议改法

分三步，都在服务层加，不要只依赖前端。

#### 1. 白名单校验后缀

```python
ALLOWED_SUFFIXES: frozenset[str] = frozenset({".txt", ".md"})

suffix: str = Path(filename).suffix.lower()
if suffix not in ALLOWED_SUFFIXES:
    raise ValidationError(message=f"不支持的文件类型: {suffix or '（无后缀）'}")
```

`ValidationError` 是项目已有的异常类，映射到 HTTP 422，会走统一响应格式，不再进 500 日志。

**白名单要按实际能力定。** 当前 `ingest_file` 只会 `read_text`，能处理的只有纯文本与 Markdown 这类 UTF-8 文本。PDF 与 Word 需要解析库（`pypdf`、`python-docx`）先把内容抽成文本，项目里没有这些依赖。所以：

| 选择 | 需要做的事 |
| --- | --- |
| 缩小前端 `accept` 到 `.txt,.md` | 改一行，前后端立刻一致 |
| 支持 PDF / Word | 新增解析依赖 + 抽取分支，前端不用改 |

**两条路必须选一条。** 保持现状（前端说支持、后端解不了）是最差的一种。

#### 2. 包住解码失败

即使后缀是 `.txt`，文件内容也可能不是 UTF-8（例如 GBK 编码的中文文本）。

```python
try:
    content: str = file_path.read_text(encoding="utf-8")
except UnicodeDecodeError as exc:
    raise ValidationError(message="文件不是 UTF-8 编码的纯文本") from exc
```

这样用户拿到的是 422 与明确文案，不是 500。

代价是磁盘上留下一个孤儿文件，需要配合「落盘文件从不回收」的清理机制。

#### 3. 前端 `accept` 与后端白名单保持一份来源

```vue
<!-- frontend/src/views/DocumentView.vue:60 -->
<input ref="fileInput" type="file" accept=".txt,.pdf,.md,.doc,.docx" style="display: none" @change="handleFileChange" />
```

`accept` 只影响文件选择器的默认过滤，不是安全边界，真正拦截必须放后端。但两处**取值应当一致**，否则用户按提示选了 PDF，收不到明确的「不支持」而是 500。

### 验证方式

按三种文件各上传一次，断言状态码：

| 文件 | 期望 |
| --- | --- |
| UTF-8 文本 `.txt` | 200 |
| 二进制内容但后缀 `.txt` | 422，文案提示编码问题 |
| 二进制内容后缀 `.pdf` | 422，文案提示类型不支持 |

对应单元测试可直接调 `DocumentService.ingest_file` 断言抛 `ValidationError`，不需要起服务。

### 备注

本问题与 frontend.md「前端产物体积过大」、下文「落盘文件从不回收」同属「上传链路的收尾工作」，建议一并处理。

`backend/tests/` 当前没有覆盖 `DocumentService.ingest_file` 的任何用例，所以这个问题在 190 个单元测试里没有被发现——`verify_*` 系列脚本也只上传 `.txt`。

## [OPEN] 17. 落盘文件从不回收，删除文档后文件残留

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 未修复 |
| 影响层 | Service 层 + Utils 层 |
| 位置 | `backend/app/services/document_service.py:98`（删除路径）；`document_service.py:51`（失败路径） |
| 首次发现 | 2026-09-22 |

### 现象

`backend/data/` 目录里的文件数量持续增长，与数据库里的 `documents` 行数不相等。

实测状态：

```
data/ 文件数: 13
DB documents 行数: 4
未被 DB 引用的文件: 9 个
```

孤儿文件里既有一个 14 字节的（上传失败留下的），也有多个 123 KB 与 1.8 KB 的（删除文档留下的）。

### 根因

文件的落盘与回收是两条不同步的路径，只有「写」没有「删」。

全项目扫过一遍，**没有任何文件删除调用**：

```bash
grep -rn "unlink\|os.remove\|shutil" backend/app/
# 无输出
```

#### 写入路径：先落盘，后校验

```python
# backend/app/services/document_service.py
51    file_path: Path = save_upload_file(
52        file_bytes=file_bytes,
53        original_filename=filename,
54    )
55    content: str = file_path.read_text(encoding="utf-8")
...
62    document: Document = self._document_repo.create(
```

`save_upload_file` 在第 51 行就把文件写进了磁盘，而任何后续步骤失败（第 55 行的解码、第 56 行的切分、第 75 行的向量化）都不会回滚这个文件。

失败时被执行过的只有：文件已在磁盘、数据库无记录、`data/` 目录多一个孤儿。

#### 删除路径：只删数据库，不删磁盘

```python
# backend/app/services/document_service.py
98    def delete_document(self, user_id: int, document_id: int) -> None:
...
105        document: Document | None = self._document_repo.get_by_id(
106            user_id=user_id,
107            document_id=document_id,
108        )
109        if document is None:
110            raise NotFoundError(message="文档不存在")
111        self._vector_repo.delete_embedding_by_document(document_id)
112        self._chunk_repo.delete_by_document(document_id)
113        self._document_repo.delete(document)
114        self._session.commit()
```

删掉了向量、切片、文档行，**没有拿 `document.file_path` 去删文件**。

`documents` 表本身有 `ON DELETE CASCADE` 指向 `users`，所以删用户会连带删掉文档行，但数据库的级联删不到文件系统上的文件。

#### 落盘的文件名不可反推

```python
# backend/app/utils/file_utils.py
23    suffix: str = Path(original_filename).suffix
24    unique_name: str = f"{uuid.uuid4().hex}{suffix}"
25    target_path: Path = data_dir / unique_name
26    target_path.write_bytes(file_bytes)
```

文件名是随机 uuid 加原后缀，与用户、文档名都无关。**要找回某个文件只能查数据库的 `file_path` 列。** 一旦数据库行被删，文件就再也没法归属到任何用户，只能整体清扫。

这意味着「删文档时忘了删文件」不是可以事后补救的错误。

### 证据

`data/` 与数据库的对照脚本：

```bash
cd /Users/jasonhuang/Desktop/trial/ai_trial/projects/agent-orchestrator

docker exec rag-postgres psql -U postgres -d rag_demo -t -A \
  -c "SELECT file_path FROM documents;" > /tmp/known.txt

python3 - <<'PY'
from pathlib import Path
known = {Path(l.strip()).name for l in Path("/tmp/known.txt").read_text().splitlines() if l.strip()}
files = [p for p in Path("backend/data").iterdir() if p.is_file()]
orphans = [p for p in files if p.name not in known]
print(f"DB 引用 {len(known)}  磁盘 {len(files)}  孤儿 {len(orphans)}")
for p in orphans:
    print(f"  {p.name}  {p.stat().st_size} bytes")
PY
```

孤儿文件的两种来源可以从大小区分：

| 大小 | 来源 |
| --- | --- |
| 十几字节 | 上传非文本文件时在解码前失败，见「上传文件未校验类型与编码」 |
| 与已知文档同尺寸 | 曾成功入库、之后被删除的文档 |

### 影响

| 影响 | 说明 |
| --- | --- |
| 磁盘只增不减 | 上传大文件后删除，空间不会释放；`.gitignore` 忽略了 `data/`，所以不会被 git 发现 |
| 隐私残留 | 用户以为删了文档，原文还在磁盘上 |
| 无法归属清理 | 文件名单调递增的 uuid，数据库行删掉后无法判断文件属于谁 |
| 备份与迁移变慢 | `data/` 会随使用时间线性膨胀 |

当前量级（9 个孤儿、约 130 KB）没有实际危害，问题在于这是只会累积的结构性缺陷。

### 建议改法

#### 1. 删除路径：先取路径，提交后删文件

```python
def delete_document(self, user_id: int, document_id: int) -> None:
    document: Document | None = self._document_repo.get_by_id(
        user_id=user_id, document_id=document_id,
    )
    if document is None:
        raise NotFoundError(message="文档不存在")

    file_path: Path = Path(document.file_path)

    self._vector_repo.delete_embedding_by_document(document_id)
    self._chunk_repo.delete_by_document(document_id)
    self._document_repo.delete(document)
    self._session.commit()

    file_path.unlink(missing_ok=True)
    cache.delete_prefix(user_retrieval_prefix(user_id))
```

要点：

| 项 | 原因 |
| --- | --- |
| 先取出 `file_path` | 提交后 ORM 对象可能失效，读不到属性 |
| 提交后再删文件 | 顺序反过来的话，删文件成功而提交失败，数据库里留了一条指向不存在文件的记录 |
| `missing_ok=True` | 文件已经不在时不该让删除接口失败 |

也可以把 `unlink` 做成仓储层的职责，与「`repositories` 只管数据库」的约定冲突，所以放在服务层更合适。

#### 2. 失败路径：用 try/except 兜住已落盘的文件

```python
file_path: Path = save_upload_file(file_bytes=file_bytes, original_filename=filename)
try:
    content: str = file_path.read_text(encoding="utf-8")
    ...  # 切分、入库、向量化
except Exception:
    file_path.unlink(missing_ok=True)
    raise
```

比这个更彻底的方案是**先校验再落盘**：解码、切分都在内存里做完，最后才写文件。这样失败时磁盘上什么都没产生。`ingest_file` 现在的顺序是「落盘 → 读回 → 切分」，中间的写回读是多余的。

#### 3. 补一个孤儿清扫入口

即使前两步做完，历史孤儿文件仍在。可以加一条 Makefile 目标：

```make
data-orphans:                         ## 列出未被数据库引用的落盘文件
	@cd $(BACKEND_DIR) && $(UV) run python scripts/list_orphan_files.py
```

**这个脚本只列出，不删除。** 删文件是不可逆操作，应当由人看过清单后手工处理。参考 `scripts/` 下现有脚本的写法（`http_e2e.py`、`verify_*.py`）。

### 验证方式

1. 上传一个 `.txt`，确认 `data/` 多一个文件、`documents` 多一行。
2. 调 `DELETE /api/v1/documents/{id}`，确认返回 200。
3. 再跑一次上面的对照脚本，孤儿数应当**没有增加**（该文件已被删除）。

失败路径的验证：上传一个二进制内容的 `.txt`，断言响应为 422，且 `data/` 文件数不变。

### 备注

本问题与「上传文件未校验类型与编码」共享同一个根因（落盘与业务记录的先后顺序），建议一并修复。

两项都建议先补 `DocumentService.ingest_file` 与 `delete_document` 的单元测试——当前 `backend/tests/` 里一个都没有，190 个用例全部集中在认证、编排、仓储与缓存上。用 `tmp_path` 夹具可以断言文件的创建与删除，见 `Backend/testing.md` 第 7 节。
