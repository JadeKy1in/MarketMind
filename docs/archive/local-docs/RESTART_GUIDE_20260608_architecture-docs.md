# RESTART GUIDE — 2026-06-08 — Architecture Documentation & Cleanup

## 1. 本会话完成事项

### 文档产出
- **MD 架构报告**：`docs/marketmind-architecture-guide.md`（43KB，10章+附录，含 Mermaid 流程图）
- **HTML 架构报告**：`docs/marketmind-architecture-guide.html`（76KB，独立文件，投行风暗色主题，Noto Serif/Sans SC 字体，打印友好）
- 报告覆盖：系统概览、10阶段Pipeline、24影子生态、3层Gate、数据流、Gateway、决策引擎、API、设计原则、运行部署

### 代码修改（3处）
| 操作 | 文件 | 原因 |
|------|------|------|
| 删除 | `ui/pause_screen.py` | 死代码——用户不会坐在屏幕前等AI分析，2分钟锁屏无意义 |
| 修改 | `ui/main_window.py` | 移除 PauseScreen 引用，Gate 2 完成后直接跳 Gate 3 |
| 修改 | `scripts/marketmind_health_check.py` | 移除 pause_screen 模块注册 |

### 概念修正（文档+代码同步）
| 修正前 | 修正后 | 依据 |
|--------|--------|------|
| Catfish 鲶鱼影子（反群体思维） | Ecosystem Auditor 盲点扫描机制，Catfish 已退役 | `shadow_metadata.py:159-164`，`ecosystem_auditor.py:3` |
| Gate 2 "强制暂停 2 分钟" | 无暂停，直接过渡到 Gate 3 | 用户确认：不会等AI做分析，交互暂停无意义 |
| Gate 3 "展示卡片→展示NoTrade→审批" | 同时展示正反两面，用户权衡后决策 | 逻辑修正：NoTrade 是不交易论证，应与交易建议并列 |
| Danziger 研究引用 | 删除——对人类行为护栏的引用在此场景不适用 | 同上 |
| 共谋检测/群体思维防范 | 集中度检测/盲点发现 | 用户确认：新影子系统没有群体思维问题 |

### 验证结果
- 全量测试：123 pass, 1 fail（唯一失败项 `test_stage1_scout_real` 为网络不通，与本次修改无关）
- Mock 模式完整流程：跑通，Stage 0-9 全部正常，早期终止逻辑正确
- 因酒店网络无法连外网，未用实际 API 模型验证完整分析链路

## 2. 当前状态

- **Branch**: master（本地，未推送）
- **Tests**: 123 pass / 1 fail（网络相关，非代码问题）
- **Pipeline mock 模式**: 正常运行
- **已删除文件**: `ui/pause_screen.py`（未提交）
- **新增文件**: MD 和 HTML 报告（未提交，untracked）
- **修改文件**: `main_window.py`, `health_check.py`（未提交）

## 3. 待办事项

| # | 任务 | 优先级 | 依赖 |
|:--:|------|:--:|------|
| 1 | 有网后用实际 API 模型跑完整 daily 流程 | 高 | VPN/网络 |
| 2 | 验证 GUI 模式 Gate 2 -> Gate 3 过渡正常 | 中 | 有 GUI 环境 |
| 3 | `git commit` 本次所有修改（代码+文档） | 中 | 任务 1 验证通过 |
| 4 | 检查 `test_pause_screen` 是否存在于测试套件中（如存在需删除） | 低 | 无 |
| 5 | 给团队讲解时收集反馈，迭代文档 | 低 | 讲解完成 |

## 4. 关键文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `docs/marketmind-architecture-guide.html` | 新 | 演示用 HTML 报告，浏览器直接打开 |
| `docs/marketmind-architecture-guide.md` | 新 | Markdown 源文件 |
| `ui/main_window.py` | 改 | 移除 pause_screen 引用，Gate 2 直通 Gate 3 |
| `ui/pause_screen.py` | 删 | 死代码 |
| `scripts/marketmind_health_check.py` | 改 | 移除 pause_screen 模块 |
| `shadows/shadow_metadata.py:159-164` | 参考 | Catfish [已退役] 标注 |
| `shadows/ecosystem_auditor.py` | 参考 | Catfish 替代机制 |

## 5. 未解决决策

- 无。本会话所有决策点已通过用户确认。

## 6. 重启第一句话（复制粘贴即可）

> 读取 `projects/marketmind/RESTART_GUIDE_20260608_architecture-docs.md`，然后按照待办事项列表继续。上次因为酒店网络不通没有跑真实API验证，这次优先解决这个问题。

**使用方式**：下次打开 Claude Code 时，直接把上面这句话发过去。它会自动读取本重启指南并接上进度。

## 7. 流程优化

### 7.1 方法论优化

| # | 发现 | 来源 | 行动 |
|:--:|------|------|------|
| 1 | **文件存在不代表功能活跃**：`catfish_agent.py` 存在但已被 `ecosystem_auditor.py` 取代，metadata 标注 [已退役]。代码探索不能只看 import 和类定义，必须查 metadata 和退役注释 | 本次错误将 Catfish 写入报告 | 探索代码时，对每个模块先查是否被替代/退役 |
| 2 | **设计文档不等于代码真相**：旧的 plan/spec md 文件中大量提到 Catfish，但代码已演进。探索必须代码优先，文档作为补充验证 | 最初引用 plan 文档中的 Catfish 概念 | 规则：代码 > metadata > orchestrator 注释 > 历史文档 |
| 3 | **行为金融学护栏只在交互场景有效**：pause_screen 的设计前提是"人坐在屏幕前逐关确认"，但实际使用是"启动后走人" | pause_screen 删除 | 设计交互功能前先确认实际使用模式 |

### 7.2 根规则更新

| 规则 | 变更 | 原因 |
|------|------|------|
| CLAUDE.md 无需更新 | — | 本次无普适性规则变更 |

### 7.3 Agent 配置

- Explore agent 在本次探索中表现良好，主 Agent 直接使用 Grep/Read 做针对性验证更高效
- 无值得模板化的新 Agent 配置

### 7.4 流程瓶颈

- **根因**：初次探索时未检查 metadata 退役标注，导致将退役概念写入报告，引发一轮返工
- **优化**：探索阶段增加"退役检查"步骤——对每个发现的模块/类，grep 搜索 `REPLACED|已退役|replaces|Phase 0` 确认活跃状态
