# LLM Wiki for AstrBot

将 LLM Wiki 作为 AstrBot 的只读知识库，支持自动检索、LLM 工具和手动查询。

## 功能

- 在普通对话请求前检索知识库，并将结果临时注入本轮上下文。
- 提供 `search_llm_wiki` 和 `read_llm_wiki_page` 两个 LLM 工具。
- 提供 `/wiki` 指令检查服务、列出项目、搜索和读取页面。
- `/wiki search` 优先使用 LLM Wiki Chat，失败时自动回退到搜索和 AstrBot 模型摘要。
- 固定使用一个 LLM Wiki 项目，避免桌面端切换项目影响机器人行为。
- 所有接口均为只读操作，不会重新索引、修改页面或写入知识库。

## 兼容性

- AstrBot：`>=4.28.1,<5`
- LLM Wiki：需要启用 Local HTTP API
- Python 依赖：使用 AstrBot 已提供的 `aiohttp`，无需额外安装

## 安装

推荐在 AstrBot WebUI 的插件市场中安装本插件。

也可以在插件管理页使用仓库地址安装：

```text
https://github.com/0oNYXo0/astrbot_plugin_llm_wiki
```

安装后重载插件，并在插件配置页填写 LLM Wiki 地址、Token 和项目。

## 快速配置

1. 在 LLM Wiki 中启用 Local HTTP API。
2. 如果 API 开启了认证，生成一个专用于 AstrBot 的 Token。
3. 在 AstrBot 插件配置中设置 `base_url` 和 `api_token`。
4. 发送 `/wiki status` 验证连接。
5. 发送 `/wiki projects` 获取项目 UUID，并将 `project_id` 固定为目标项目。
6. 发送 `/wiki search 测试问题` 验证 Chat 和搜索流程。

`base_url` 只填写服务根地址，不要附加 `/api/v1`。AstrBot 使用 Docker 时，`127.0.0.1` 指向容器自身，应填写容器可访问的宿主机地址或服务名。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `base_url` | `http://127.0.0.1:19828` | LLM Wiki API 根地址，不含 `/api/v1` |
| `api_token` | 空 | API 开启认证时必填；在 WebUI 中按敏感字段存储 |
| `project_id` | `current` | 推荐填写固定项目 UUID；也支持 `current` 或绝对路径 |
| `auto_retrieval` | `true` | 普通 LLM 请求前自动检索知识库 |
| `enable_llm_tools` | `true` | 允许 AstrBot 模型调用搜索和页面读取工具 |
| `chat_enabled` | `true` | `/wiki search` 优先调用 LLM Wiki Chat |
| `summary_threshold` | `4000` | 回退搜索文本超过该字符数时调用 AstrBot 模型摘要 |
| `top_k` | `5` | 每次搜索结果数，运行时限制为 1-20 |
| `request_timeout` | `15` | HTTP 请求超时秒数，运行时限制为 1-120 |
| `max_context_chars` | `8000` | 自动注入上下文的最大字符数 |
| `max_page_chars` | `20000` | 页面读取和手动搜索的最终输出上限 |

## 指令

```text
/wiki status
/wiki projects
/wiki search <关键词或问题>
/wiki read <wiki/...页面路径>
/wiki help
```

- `/wiki status`：检查 API 状态、版本、认证要求和当前配置的项目。
- `/wiki projects`：列出可用项目及项目 UUID。
- `/wiki search`：查询固定项目并返回回答及来源。
- `/wiki read`：读取搜索结果中的 `wiki/` 页面；其他路径会被拒绝。

### 手动搜索降级顺序

1. 调用 LLM Wiki Chat，由 LLM Wiki 检索、读取并回答。
2. Chat 不可用或 `chat_enabled=false` 时调用搜索接口。
3. 搜索文本超过 `summary_threshold` 时，使用当前 AstrBot 会话模型生成摘要。
4. AstrBot 未配置模型、摘要失败或返回空内容时，返回原始搜索结果。

Chat 请求仅启用 Wiki 工具，关闭 Web 和 AnyTXT，并设置 `persistSession=false`。所有最终输出均受 `max_page_chars` 限制。

## 自动检索

启用 `auto_retrieval` 后，插件会在普通 LLM 请求前搜索固定项目，并把结果作为临时 `TextPart` 注入当前请求。检索内容不会写入会话历史，知识库不可用时也不会阻断正常对话。

以下消息不会触发自动检索：

- 空消息
- 少于 3 个字符的消息
- 以 `/` 开头的指令

## LLM 工具

- `search_llm_wiki(query)`：返回标题、摘要和来源路径。
- `read_llm_wiki_page(path)`：读取搜索结果中的 `wiki/` 页面。

工具结果会返回给 AstrBot 当前模型继续推理，不会直接替代模型回答。设置 `enable_llm_tools=false` 可停用两个工具。

## API 与安全

插件只调用以下接口：

- `GET /api/v1/health`
- `GET /api/v1/projects`
- `POST /api/v1/projects/{id}/search`
- `POST /api/v1/projects/{id}/chat`
- `GET /api/v1/projects/{id}/files/content`

安全建议：

- 不要把真实 Token 写入 README、日志、Issue、截图或提交到 Git。
- 为 AstrBot 使用独立 Token，并按最小权限原则配置。
- 不要将未启用认证的 LLM Wiki API 暴露到公网。
- 知识库内容会作为不可信参考资料传给模型，不会被当作系统指令执行。
- 插件不会记录或返回配置的 Token。

## 故障排查

| 现象 | 处理方式 |
| --- | --- |
| `Cannot connect` | 检查 LLM Wiki 是否运行、`base_url` 是否可从 AstrBot 主机或容器访问 |
| `401` | 确认 API 已生成有效 Token，并重新填写 `api_token` |
| `404` | 检查 `project_id` 或 `wiki/` 页面路径 |
| `503` | 确认 LLM Wiki Local HTTP API 已启用，稍后重试 |
| Chat 回退到搜索 | 检查 Token、项目和 LLM Wiki Chat 配置；回退不影响基础搜索 |
| 没有自动检索 | 检查 `auto_retrieval`、固定项目和搜索结果 |
| 没有 AstrBot 摘要 | 确认当前会话已配置可用的聊天模型 |

## 开发验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
ruff check .
ruff format --check .
```

## 许可证

[GNU Affero General Public License v3.0](LICENSE)
