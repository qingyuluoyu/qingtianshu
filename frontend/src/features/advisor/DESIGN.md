# 金融顾问（/advisor/:conversationId?）组件设计记录

执行合同：FRONTEND_EXECUTION_CONTRACT_V1（§5.5 金融顾问蓝图、§4 共享组件、§6 数据/时间/金融口径、§7 互动与写入边界、§8 禁止约定）。
本切片写操作范围：发送问题（`POST /me/chat`）与 AI 候选确认/拒绝（`POST /v1/ai-writebacks/{id}/confirm|reject`）。
后端无候选 PATCH → 候选卡只有查看/确认/拒绝/回到对话修改，**没有编辑按钮**。

## 数据契约总表

| 用途 | 接口 | 关键字段 | 时间类型（§6.2） |
| --- | --- | --- | --- |
| 会话列表 | `GET /me/conversations` | `items[*].{id,title,status,message_count,last_message_preview,last_intent,conversation_scope,research_targets,created_at,updated_at}` | 列表时间 = `updated_at` |
| 会话历史 | `GET /me/conversations/{conversation_id}` | 上述 + `messages[*].{id,role,content,intent,run_id,metadata,created_at}`；`metadata.{symbol,model_tier,evidence_sources,structured_answer}` | GeneratedAt = `messages[*].created_at`；证据时间 = `evidence_sources[*].as_of` |
| 提问（写） | `POST /me/chat` | 请求 `{message,symbol,conversation_id,request_id}`；响应 `{run_id,status,intent,model_tier,answer,evidence,error,conversation_id,assistant_message_id,evidence_sources,research_targets,structured_answer}` | — |
| 生成进度 | `GET /me/chat/stream/{request_id}`（SSE，不在 openapi） | 事件 `{type:agent_progress,phase,label}` | — |
| 候选写回 | `GET /v1/ai-writebacks`（contract `structured_ai_response_v1`） | `items[*].{id,symbol,candidate_type,status,payload,citation_ids,base_version,created_at,resolved_at}`、`summary.{total,pending_confirmation}` | GeneratedAt = `created_at`；处理时间 = `resolved_at` |
| 候选确认/拒绝（写） | `POST /v1/ai-writebacks/{candidate_id}/confirm|reject` | 无请求体；版本 `base_version` 由服务端内嵌校验，409 = `StructuredAIConflict`（候选被服务端置 `stale`） | — |

金融口径与直通：
- 本页不呈现任何行情数字；百分数/价格不出现在顾问页，无缩放问题。
- `message_count=0` 是有效数值正常显示；`null`（缺字段）显示 `--`；空列表 → 「还没有研究对话」；接口失败 → 模块级错误卡 + 重试。四态严格分开（§6.3）。
- 状态翻译只映射后端状态：`pending_confirmation→待确认草稿`、`confirmed/rejected/stale/failed/clarification/blocked/partial/complete` 等按 §6.3 色系；未知状态原样展示。

### §5.5 上下文携带的落点

- URL 接收 `symbol`、`sourcePage`（兼容现有入口的 `source`）、`module`、`asOf`、`question`、`intent` 六类参数；ContextBar 直通展示，不补造缺失值。
- 后端 `ChatRequest` 只有 `symbol` 专用字段（openapi 实测），`sourcePage/module/asOf` 没有传输字段。按 §5.5「每次问顾问必须携带上下文」，前端把四元组拼成可追溯上下文行 `[研究上下文：标的=…；来源页=…；模块=…；数据时间=…]` 附在用户消息正文后（随消息落库可审计），`symbol` 同时走专用字段。这是合同要求与后端 Schema 差距下的唯一真实通道，DESIGN 记录此缺口：后端若新增上下文字段，应改为专用字段传输。
- `?question=` 与 `?intent=new-thesis|deep-research` 只预填草稿，**绝不自动发送**；用户发送后才创建 Run（§5.5）。

### SSE 处理

- 发送时生成 `request_id`（crypto.randomUUID），先开 `EventSource(/me/chat/stream/{request_id})` 再 POST；`agent_progress.label` 更新生成中占位气泡文案。
- EventSource 不存在（jsdom）或流 404/断开时静默降级为固定进度文案；完整回答始终以 POST 同步响应为准，SSE 只做进度增强。
- e2e mock 模式对 stream 路由返回 404，覆盖降级路径。

### 候选写回边界（§5.5/§7.2）

- 候选来源：`GET /v1/ai-writebacks`（当前状态真相）+ 历史消息 `metadata.structured_answer.candidate_writebacks`（生成时点快照，仅经抽屉展示上下文）。
- 确认走二次对话框（ConfirmDialog），文案明确影响对象、`base_version` 版本号与冲突语义；拒绝单步执行。
- 版本字段由服务端内嵌校验（confirm 无 `expected_version` 请求字段，openapi 实测）；409 时前端不做任何本地覆盖，失效重拉候选列表取回 `stale` 最新状态，提示用户回到对话重新生成。
- 写操作四态：pending（按钮禁用「写入中…」）/ success（提示 + 失效重取）/ failed（提示可重试）/ conflict（409 分支）。
- 「回到对话修改」把候选类型与标的预填进输入框并聚焦，由用户改写后重新提问；候选本身无编辑入口。

### ConversationSidebar（会话列表与上下文）
- 页面与用户问题：我有哪些研究对话？这次提问带着什么页面上下文？
- 真实数据：`GET /me/conversations`；上下文来自 URL searchParams（不发请求）。
- 状态：loading=侧栏内骨架省略（页级已有）；空=「还没有研究对话」真实空态；失败=侧栏模块级错误卡 + 重试，不影响主列。
- 互动事件：点击会话切路由 `/advisor/:conversationId`（保留 searchParams）；「开始新对话」回 `/advisor`（不预创建空会话，发送后由后端创建）。
- 响应式：≥1280 左栏 280px；<820 堆叠到顶部、列表限高滚动。
- 测试：Page 测试列表渲染、`0 条消息` 直通、上下文四元组、空态。

### ContextBar（已收集上下文）
- 真实数据：URL `symbol/sourcePage(source)/module/asOf` 直通；`source` 经固定映射翻译（watchlist→我的关注 等），未知值原样展示。
- 状态：四元组全缺时显示「未携带页面上下文」说明，不显示假上下文。
- 测试：Page 测试四元组与缺省文案。

### MessageStream（消息流）
- 页面与用户问题：这轮对话问了什么、回答是什么、什么时候生成的？
- 真实数据：会话详情 `messages[*]`；每条助手消息带 GeneratedAt（`created_at`）、意图、标的。
- 状态：空会话=「输入第一个问题…」；详情 404/失败=模块错误卡 + 重试；发送中=临时用户气泡 + 顾问占位气泡（SSE 进度文案）。
- 互动事件：「查看证据与五面分析」仅选中该消息喂给 EvidenceDrawer，不改路由。
- 测试：Page 测试消息直通、生成时间、预填不自动发送、发送载荷（symbol/conversation_id/request_id/上下文行）。

### ClarifyingQuestionFlow（问题澄清）
- 真实数据：`POST /me/chat` 响应 `status="clarification"` 且 `evidence.required_fields` 非空时渲染；字段直通，不自行编造问题。
- 互动事件：提示用户在输入框补充后再次发送；不提供额外表单（无对应后端字段）。
- 测试：Page 测试 required_fields 渲染。

### EvidenceDrawer（证据与候选写回抽屉）
- 页面与用户问题：这条回答的证据、五面分析和待确认候选是什么？
- 真实数据：选中（或最近一条带证据的）助手消息 `metadata.{evidence_sources,structured_answer}` + `GET /v1/ai-writebacks`。
- 可见条件：候选非空 **或** 存在带证据的助手消息才渲染；两者皆无**不渲染空壳**（合同 §5.5/§8）。
- 状态：候选按 `pending_confirmation→stale→其他` 排序，上限 20 条；`structured_answer.status` 按 §6.3 翻译。
- 响应式：≥1280 右栏 370px；820-1279 降为两列卡片区；<820 单列置于主列下方。
- 测试：Page 测试五面分析、证据来源、无数据不渲染抽屉。

### FiveFactorAnalysis（五面分析）
- 真实数据：`structured_answer`（contract `structured_ai_response_v1`，version 不符抛 ContractError）：已确认事实/证据支持的推断/待核验假设/反方证据与风险/信息缺口 + `conclusion_boundary` 边界原文。
- 状态：空组显示「暂无记录」，与不可用区分。

### WritebackCandidateCard（候选写回卡片）
- 写入边界：见上文「候选写回边界」；payload 按类型直通（thesis/observation_task/action_plan 映射字段名，未知类型只列原始键值），不编造结构。
- 测试：Page 测试确认对话框版本文案、确认/拒绝调用、409 冲突、回到对话修改预填、无编辑按钮。

## 验收记录

- `npx vitest run src/features/advisor`：20/20 通过（adapters 10 + Page 10）；全量 `npx vitest run` 146/146 通过。
- `npx tsc --noEmit`：通过。
- `npx playwright test e2e/advisor.spec.ts`：3/3 通过（主链路+发送载荷断言、候选确认 409、390px 无横向溢出）。
- 真实会话截图：`today-runtime-trace/screenshots/advisor-desktop.png`（1440×900）、`advisor-mobile.png`（390×844），两视口横向溢出 0px；验收账号 acceptance01 会话与候选均为空，截图覆盖真实空态（无抽屉空壳、上下文缺省说明）。未在真实后端发送任何提问。
- 遗留缺口：① `sourcePage/module/asOf` 无后端专用字段，暂以消息正文上下文行携带（见 §5.5 落点）；② 候选与具体消息的关联只靠 `metadata.structured_answer.candidate_writebacks` 快照，列表真相以 `/v1/ai-writebacks` 为准；③ SSE 在 e2e mock 模式只覆盖 404 降级路径，未模拟进度事件流。
