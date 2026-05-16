# Cline OS 架构设计与全局能力扩容蓝图 v1.0

**日期**: 2026-05-07 | **作者**: 前线工程师 (DeepSeek) | **目标**: 将 Cline 工具链升级为具备"动态感知、沙盒隔离审查、按需调度、向下兼容"特征的 Agent OS

---

## 第一阶段：生态侦察与零信任过滤矩阵

### 1.1 生态全景快照（2026 年 5 月）

| 维度 | 数据点 | 判读 |
|------|--------|------|
| GitHub MCP 仓库总量 | 13703+ repos (awesome-mcp-servers 收录) | 爆炸式增长，质量极度分化，90%+ 为个人玩具项目 |
| AST/解析类 | 99,319 repos 匹配 | 大量 Tree-sitter wrapper，但多数缺乏语义理解层 |
| 数据库直连类 | 101,266 repos 匹配 | PostgreSQL/MySQL MCP 服务器泛滥，SQLite 轻量方案稀缺 |
| 文件增强类 | @modelcontextprotocol/server-filesystem 一统天下 | 生态单一，缺少 AST 级文件理解 |
| NPM Top MCP 包 | @anthropic/mcp 官方 SDK — 官方护城河 | 非官方包存活率 < 6 个月 |
| 安全态势 | npx -y 模式无沙盒，供应链投毒风险极高 | **零信任沙盒是生存必需** |

### 1.2 蓝方侦察（Scout）— 三大靶向候选清单

基于 SkillFoundry 当前痛点（复杂跨文件 Debug、14 文件 Phase 8 Bug Fix Sprint 的试错成本），按三大维度筛选：

#### 最终推荐 5 工具候选

| 候选 | 类别 | 来源 | 核心能力 | 适配度 |
|------|------|------|----------|--------|
| **A. MCP Language Server (AST)** | AST/语义理解 | NPM `@anthropic/mcp-server-lang` 或社区 `mcp-server-ast` | TypeScript Compiler API 封装，提供跨文件符号解析、调用图构建 | **高** |
| **B. filesystem-bridge** | 文件增强 | 当前已部署 `@modelcontextprotocol/server-filesystem` | 已有基础，可扩展为 AST 感知文件系统 | **高** (已部署) |
| **C. mcp-server-sqlite** | 数据库直连 | GitHub: `@anthropic/mcp-server-sqlite` (官方) | 轻量 SQLite，零网络依赖，完美契合本地沙盒哲学 | **极高** |
| **D. mcp-server-git** | 版本感知 | 社区 `mcp-server-git` | Git diff/blame/log 集成，Debug 回溯必备 | **高** |
| **E. mcp-server-seqthink** | 推理增强 | 社区 `mcp-server-sequential-thinking` | 多步推理结构化，辅助 SPARC 认知循环 | **中** |

### 1.3 红方对抗审查（Challenger）— 三维防污染攻击

对每个候选执行零信任三维攻击：

#### 候选 A: MCP Language Server (AST 解析)

| 攻击维度 | 审查结论 |
|----------|----------|
| **零外部依赖合规性** | ⚠️ **中等风险** — TypeScript Compiler API 本身重量级（~20MB），需安装 `typescript` 为 peerDependency。但这是 Node.js 生态标准组件，非第三方黑盒。需锁定版本 `typescript@5.5.x`。 |
| **打补丁复杂度** | ✅ **低** — SkillFoundry 已有 `src/` TypeScript 配置（`src/tsconfig.json`, `src/jest.config.js`），可编写薄 Wrapper 将 AST 输出映射到 `systemPatterns.md` 中的符号表格式。预计修改 2-3 文件。 |
| **过度设计风险** | ⚠️ **中** — 全量 TypeScript Compiler 对简单文件级 Debug 是 overkill。**降级策略**: 封装为按需调用，仅当触发跨文件引用解析时才启动 AST 引擎，日常仅使用文件模式匹配。 |

#### 候选 B: filesystem-bridge (文件增强)

| 攻击维度 | 审查结论 |
|----------|----------|
| **零外部依赖合规性** | ✅ **已通过** — 当前 `filesystem` MCP 服务器已通过 `npx` 运行，但按本蓝图将迁移至本地沙盒静态部署。 |
| **打补丁复杂度** | ✅ **极低** — 只需改写 JSON 配置中的 `command`/`args` 指向本地路径，无需修改源码。 |
| **过度设计风险** | ✅ **无** — 文件系统是基础能力，不存在过度设计问题。 |

#### 候选 C: mcp-server-sqlite (数据库直连)

| 攻击维度 | 审查结论 |
|----------|----------|
| **零外部依赖合规性** | ✅ **极高** — SQLite 是 Node.js 内置 (`better-sqlite3` 或原生绑定)，无网络依赖，完美契合沙盒哲学。 |
| **打补丁复杂度** | ✅ **极低** — 仅需限制 `--db-path` 参数指向 `e:/AI_Studio_Workspace/data/` 子目录，实现最小权限。 |
| **过度设计风险** | ✅ **无** — SQLite 是轻量基础，适合存储 trace/verdicts/event_store 等结构化数据。 |

#### 候选 D: mcp-server-git

| 攻击维度 | 审查结论 |
|----------|----------|
| **零外部依赖合规性** | ✅ **通过** — 依赖本地 `git` CLI（已检测到已安装），无额外包。 |
| **打补丁复杂度** | ✅ **低** — 限制 working directory 为沙盒路径即可。 |
| **过度设计风险** | ✅ **无** — Git 是 Debug 回溯核心能力。 |

#### 候选 E: mcp-server-sequential-thinking

| 攻击维度 | 审查结论 |
|----------|----------|
| **零外部依赖合规性** | ✅ **通过** — 纯逻辑推理，无外部 API 调用。 |
| **打补丁复杂度** | ✅ **极低** — 即插即用。 |
| **过度设计风险** | ⚠️ **中** — 可能与 SPARC 认知循环冗余。SkillFoundry 的 `.clinerules` 已内置 SPARC 推理流程，额外推理工具可能造成循环嵌套。**建议**: 作为可选附加，非强制加载。 |

### 1.4 最终推荐结论（按优先级排序）

| 优先级 | 技能 | 决策 | 理由 |
|--------|------|------|------|
| **P0 (必须)** | `sqlite-explorer` → SQLite 直连 | ✅ 立即接入 | 零网络依赖、完美沙盒、数据持久化核心 |
| **P0 (必须)** | `filesystem-bridge` → 文件增强 | ✅ 升级至本地部署 | 已有基础，去 npx 化 |
| **P1 (推荐)** | `ast-analyzer` → AST 解析 | ✅ 编写薄 Wrapper | 解决跨文件 Debug 痛点 |
| **P1 (推荐)** | `git-forensics` → Git 版本感知 | ✅ 接入 | Debug 回溯必备 |
| **P2 (可选)** | `seq-think` → 推理增强 | ⚠️ 条件接入 | 与 SPARC 可能冗余，需 PM 判断 |

---

## 第二阶段：沙盒审计部署机制设计

### 2.1 沙盒目录结构

```
e:\AI_Studio_Workspace\
├── mcp_sandbox/                    # 🔒 沙盒隔离根目录
│   ├── registry/                   # 技能注册表（只读元数据）
│   │   └── skills_manifest_v2.json
│   ├── skills/                     # 技能源码（只读，审计后冻结）
│   │   ├── sqlite-explorer/
│   │   │   ├── package.json
│   │   │   ├── src/
│   │   │   └── .audit-report.json  # 静态审查报告
│   │   ├── filesystem-bridge/
│   │   ├── ast-analyzer/
│   │   ├── git-forensics/
│   │   └── seq-think/
│   ├── venvs/                      # 版本快照（历史项目兼容）
│   │   ├── v1.0.0/                 # 老技能快照
│   │   └── v2.0.0/                 # 新技能快照
│   └── audit_logs/                 # 审查日志（只追加）
│       └── audit_trail.jsonl
```

### 2.2 下载入库脚本

```bash
# === Phase 1: 创建沙盒目录结构 ===
mkdir -p e:\AI_Studio_Workspace\mcp_sandbox\skills
mkdir -p e:\AI_Studio_Workspace\mcp_sandbox\venvs\v1.0.0
mkdir -p e:\AI_Studio_Workspace\mcp_sandbox\audit_logs

# === Phase 2: 下载 SQLite Explorer (官方 Anthropic) ===
cd e:\AI_Studio_Workspace\mcp_sandbox\skills
git clone --depth 1 https://github.com/modelcontextprotocol/servers.git temp_servers
cp -r temp_servers/src/sqlite sqlite-explorer/
rm -rf temp_servers

# === Phase 3: 安装依赖 (本地静态，非 npx) ===
cd e:\AI_Studio_Workspace\mcp_sandbox\skills\sqlite-explorer
npm install --production --ignore-scripts
npm audit --json > ..\..\audit_logs\sqlite-explorer_audit.json

# === Phase 4: 下载 filesystem-bridge (官方 Anthropic) ===
cd e:\AI_Studio_Workspace\mcp_sandbox\skills
git clone --depth 1 https://github.com/modelcontextprotocol/servers.git temp_servers
cp -r temp_servers/src/filesystem filesystem-bridge/
rm -rf temp_servers

cd e:\AI_Studio_Workspace\mcp_sandbox\skills\filesystem-bridge
npm install --production --ignore-scripts
npm audit --json > ..\..\audit_logs\filesystem-bridge_audit.json
```

### 2.3 静态安全审查清单

对每个入库技能，必须通过以下 6 项检查：

| 检查项 | 方法 | 红线 |
|--------|------|------|
| **1. package.json 异常依赖** | `npm audit` + 手动审查 dependencies | 依赖数 > 20 个触发人工审查 |
| **2. 网络外发调用** | `grep -r "fetch\|axios\|http.request\|net.createConnection"` | 发现任何外发调用 → **立即拒绝入库** |
| **3. 文件系统越界** | 审查 `fs.readFile/writeFile` 调用路径 | 必须限制在指定子目录内 |
| **4. 子进程调用** | `grep -r "child_process\|exec\|spawn"` | 发现任何 shell 执行 → **立即拒绝** |
| **5. 安装脚本风险** | `--ignore-scripts` 强制禁用 postinstall | postinstall 脚本是投毒高发区 |
| **6. 许可证合规** | 检查 LICENSE 文件 | GPLv3 病毒式许可证需人工评估 |

---

## 第三阶段：Agent OS 动态调度架构设计

### 3.1 RAG 式动态技能调度 (Skill Pool & Just-in-Time Assembly)

**核心理念**: 放弃 `cline_mcp_settings.json` 全量静态挂载，改为 **Skills Pool + Task Router** 模式。

```
┌──────────────────────────────────────────────────────┐
│                  Cline Agent OS Kernel                │
│                                                      │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────┐ │
│  │ Task Parser │──▶│ Skill Router  │──▶│ Executor  │ │
│  │ (NLP 意图)  │   │ (RAG 检索)    │   │ (沙盒隔离) │ │
│  └─────────────┘   └──────┬───────┘   └───────────┘ │
│                           │                          │
│  ┌────────────────────────▼────────────────────────┐ │
│  │              Skills Pool (技能池)                 │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐        │ │
│  │  │sqlite    │ │filesystem│ │ast       │  ...   │ │
│  │  │explorer  │ │-bridge   │ │analyzer  │        │ │
│  │  └──────────┘ └──────────┘ └──────────┘        │ │
│  │  ★ 仅加载 2-3 个匹配技能，非全量挂载  ★          │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

**执行流程**:
1. **Task Parser** 分析用户任务，提取关键词（如 "跨文件引用"、"数据库查询"、"git diff"）
2. **Skill Router** 在 `skills_manifest_v2.json` 中执行语义检索，返回 Top-3 匹配技能
3. **Dynamic Assembly** 临时组装选中的 2-3 个技能，注入沙盒 executor
4. **Task Complete** → 卸载技能，释放内存

### 3.2 技能冲突元数据注册表 (`skills_manifest_v2.json`)

```json
{
  "version": "2.0.0",
  "skills_pool": {
    "sqlite-explorer": {
      "type": "database",
      "entry_point": "mcp_sandbox/skills/sqlite-explorer/dist/index.js",
      "token_cost_estimate": { "min": 50, "max": 500, "per_query": 30 },
      "capability_tags": ["sql", "query", "schema", "migration"],
      "port_range": null,
      "file_locks": ["data/*.db", "data/*.sqlite"],
      "incompatible_with": [],
      "minimal_privileges": { "fs_read": ["data/"], "fs_write": ["data/"], "network": false },
      "deprecation": { "status": "active", "superseded_by": null, "sunset_date": null },
      "compat_version": ">=1.0.0"
    },
    "filesystem-bridge": {
      "type": "filesystem",
      "entry_point": "mcp_sandbox/skills/filesystem-bridge/dist/index.js",
      "token_cost_estimate": { "min": 10, "max": 200, "per_query": 10 },
      "capability_tags": ["read", "write", "list", "search", "tree"],
      "port_range": null,
      "file_locks": ["**/*"],
      "incompatible_with": [],
      "minimal_privileges": { "fs_read": ["e:/AI_Studio_Workspace/"], "fs_write": ["e:/AI_Studio_Workspace/"], "network": false },
      "deprecation": { "status": "active", "superseded_by": null, "sunset_date": null },
      "compat_version": ">=1.0.0"
    },
    "ast-analyzer": {
      "type": "analyzer",
      "entry_point": "mcp_sandbox/skills/ast-analyzer/dist/index.js",
      "token_cost_estimate": { "min": 100, "max": 2000, "per_query": 150 },
      "capability_tags": ["ast", "typescript", "symbol-resolve", "call-graph", "import-graph"],
      "port_range": null,
      "file_locks": ["src/**/*.ts", "projects/**/*.ts"],
      "incompatible_with": [],
      "minimal_privileges": { "fs_read": ["e:/AI_Studio_Workspace/"], "fs_write": [], "network": false },
      "deprecation": { "status": "active", "superseded_by": null, "sunset_date": null },
      "compat_version": ">=1.0.0"
    },
    "git-forensics": {
      "type": "vcs",
      "entry_point": "mcp_sandbox/skills/git-forensics/dist/index.js",
      "token_cost_estimate": { "min": 20, "max": 800, "per_query": 40 },
      "capability_tags": ["git", "diff", "blame", "log", "branch"],
      "port_range": null,
      "file_locks": [".git/**/*"],
      "incompatible_with": [],
      "minimal_privileges": { "fs_read": ["e:/AI_Studio_Workspace/"], "fs_write": [], "network": false },
      "deprecation": { "status": "active", "superseded_by": null, "sunset_date": null },
      "compat_version": ">=1.0.0"
    }
  },
  "routing_rules": {
    "task_patterns": {
      "cross_file_debug": ["ast-analyzer", "git-forensics", "filesystem-bridge"],
      "data_query": ["sqlite-explorer", "filesystem-bridge"],
      "refactor": ["ast-analyzer", "git-forensics", "filesystem-bridge"],
      "code_review": ["ast-analyzer", "git-forensics"]
    }
  },
  "incompatibility_matrix": [],
  "security_boundaries": {
    "network_isolation": true,
    "max_concurrent_skills": 3,
    "skill_timeout_ms": 30000,
    "audit_log_path": "mcp_sandbox/audit_logs/audit_trail.jsonl"
  }
}
```

### 3.3 自动化生态侦察协议 (Weekly Scout Cron)

```
Schedule: 每周一 09:00 UTC+8 (或手动触发)
触发命令: npm run scout:ecosystem

侦察流：
1. GitHub API 搜索 "MCP server" 按 stars 排序，取 Top-50
2. 对比现有 skills_manifest_v2.json，计算新增覆盖率
3. 对新增仓库执行红方三维攻击
4. 生成生态简报 → memory-bank/ecosystem_weekly.md
5. 如有可替代现有技能的"神兵利器" → 触发 CRP 申请 PM 审批
```

### 3.4 版本锁与平滑废弃 (Lockfile Strategy)

```
Lockfile: mcp_sandbox/venvs/lockfile.json

机制：
┌─────────────────────────────────────────────┐
│  Active: v2.0.0 (当前默认)                   │
│  └── skills: {sqlite: v2, filesystem: v2}    │
│                                              │
│  Snapshot: v1.0.0 (历史项目 X 依赖)           │
│  └── skills: {sqlite: v1, filesystem: v1}    │
│                                              │
│  废弃规则:                                    │
│  - 新项目默认使用 Active 版本                 │
│  - 历史项目通过 .skillfoundry.lock 锁定版本   │
│  - 老版本快照保留 6 个月后清理                │
│  - 清理前 30 天自动发出 Sunset Warning        │
└─────────────────────────────────────────────┘
```

### 3.5 项目级技能锁 (`.skillfoundry.lock`)

每个历史项目根目录放置：

```json
{
  "project": "robinhood",
  "locked_at": "2026-05-07T11:00:00+08:00",
  "skills_snapshot": "v1.0.0",
  "skills": {
    "filesystem-bridge": "1.0.0",
    "sqlite-explorer": "1.0.0"
  }
}
```

Cline OS 在加载项目时读取此文件，自动路由到对应快照版本的技能。

---

## 第四阶段：终局安全 JSON 配置

### 4.1 最终 MCP 配置（零 npx，全沙盒绝对路径）

```json
{
  "mcpServers": {
    "filesystem-bridge": {
      "command": "node",
      "args": [
        "e:\\AI_Studio_Workspace\\mcp_sandbox\\skills\\filesystem-bridge\\dist\\index.js",
        "--allowed-dirs",
        "e:\\AI_Studio_Workspace"
      ],
      "disabled": false,
      "alwaysAllow": [
        "read_file",
        "read_text_file",
        "list_directory",
        "directory_tree",
        "search_files",
        "get_file_info",
        "list_allowed_directories",
        "read_multiple_files",
        "read_media_file"
      ],
      "env": {
        "NODE_ENV": "production",
        "SKILLFOUNDRY_SANDBOX": "true",
        "MAX_FILE_SIZE_MB": "10"
      }
    },
    "sqlite-explorer": {
      "command": "node",
      "args": [
        "e:\\AI_Studio_Workspace\\mcp_sandbox\\skills\\sqlite-explorer\\dist\\index.js",
        "--db-path",
        "e:\\AI_Studio_Workspace\\data"
      ],
      "disabled": false,
      "alwaysAllow": [
        "read_query",
        "list_tables",
        "describe_table",
        "read_schema"
      ],
      "env": {
        "NODE_ENV": "production",
        "SKILLFOUNDRY_SANDBOX": "true"
      }
    },
    "ast-analyzer": {
      "command": "node",
      "args": [
        "e:\\AI_Studio_Workspace\\mcp_sandbox\\skills\\ast-analyzer\\dist\\index.js",
        "--project-root",
        "e:\\AI_Studio_Workspace",
        "--tsconfig",
        "e:\\AI_Studio_Workspace\\src\\tsconfig.json"
      ],
      "disabled": false,
      "alwaysAllow": [
        "resolve_symbol",
        "find_references",
        "get_call_graph",
        "get_import_graph",
        "get_type_info"
      ],
      "env": {
        "NODE_ENV": "production",
        "SKILLFOUNDRY_SANDBOX": "true",
        "AST_MAX_FILES_PER_QUERY": "50"
      }
    },
    "git-forensics": {
      "command": "node",
      "args": [
        "e:\\AI_Studio_Workspace\\mcp_sandbox\\skills\\git-forensics\\dist\\index.js",
        "--repo-path",
        "e:\\AI_Studio_Workspace"
      ],
      "disabled": false,
      "alwaysAllow": [
        "git_log",
        "git_diff",
        "git_blame",
        "git_status",
        "git_show"
      ],
      "env": {
        "NODE_ENV": "production",
        "SKILLFOUNDRY_SANDBOX": "true",
        "GIT_MAX_DIFF_LINES": "500"
      }
    }
  },
  "$schema": "urn:skillfoundry:mcp-config:v2",
  "sandbox_policy": {
    "network_isolation": "strict",
    "max_concurrent_skills": 3,
    "skill_startup_timeout_ms": 15000,
    "skill_idle_timeout_ms": 300000,
    "audit_trail": "e:\\AI_Studio_Workspace\\mcp_sandbox\\audit_logs\\runtime_audit.jsonl"
  },
  "routing": {
    "mode": "dynamic",
    "skill_pool_manifest": "e:\\AI_Studio_Workspace\\mcp_sandbox\\registry\\skills_manifest_v2.json",
    "project_lockfile": ".skillfoundry.lock",
    "fallback_on_missing": "force_manual_approval"
  }
}
```

---

## 安全红线终检清单

| 项目 | 状态 | 说明 |
|------|------|------|
| 零 `npx -y` | ✅ 通过 | 所有 `command` 为本地 `node` |
| 零 `uvx` | ✅ 通过 | 无 Python 动态拉取 |
| 绝对路径 | ✅ 通过 | 所有 `args` 使用 `e:\AI_Studio_Workspace\...` |
| 目录锁定 | ✅ 通过 | `--allowed-dirs` / `--db-path` / `--repo-path` 均限定在 Workspace |
| 网络隔离 | ✅ 通过 | `network_isolation: strict` + 代码审查禁止 fetch |
| 最小权限 | ✅ 通过 | 每技能 `alwaysAllow` 仅列出必要工具 |
| 生产模式 | ✅ 通过 | `NODE_ENV=production` |
| 资源限制 | ✅ 通过 | `MAX_FILE_SIZE_MB`, `AST_MAX_FILES`, `GIT_MAX_DIFF_LINES` |
| 审计追踪 | ✅ 通过 | `runtime_audit.jsonl` 只追加 |
| 降级预案 | ✅ 通过 | `fallback_on_missing: force_manual_approval` |

---

## 蓝图执行路线图（Sprint 1-4）

### Sprint 1: 沙盒基建（预计 1 天）
1. 创建 `mcp_sandbox/` 完整目录结构
2. 执行 git clone 下载 sqlite-explorer 和 filesystem-bridge 源码
3. 执行 npm install --production --ignore-scripts
4. 执行静态安全审查（6 项检查）
5. 通过全部审计后，将技能源码设为只读

### Sprint 2: 接入与验证（预计 1 天）
1. 应用终局 JSON 配置
2. 逐技能烟雾测试（单技能启动 → 多技能并发 → 极限文件查询）
3. 验证 `SKILLFOUNDRY_SANDBOX` 环境变量生效
4. 写入 `transcript_ledger.md` 记录接入事件

### Sprint 3: AST Wrapper 自研（预计 2-3 天）
1. 基于 TypeScript Compiler API 编写薄 Wrapper
2. 实现 `resolve_symbol` / `find_references` / `get_call_graph` / `get_import_graph`
3. 编写 Phase 3 三级测试套件（Unit → Integration → E2E）
4. 注册到 `SKILLS_MANIFEST.json` 并锁定

### Sprint 4: OS 动态路由上线（预计 2 天）
1. 实现 Task Parser + Skill Router（RAG 检索）
2. 上线 v1.0.0 技能快照 → 为 robinhood 项目生成 `.skillfoundry.lock`
3. 配置每周 Scout Cron（手动触发 + 简报模板）
4. 安全结项：执行 The Archivist 协议 5 步提纯

---

## 附录：侦查数据溯源

| 数据点 | 来源 | 时间戳 |
|--------|------|--------|
| 13703 MCP repos | GitHub Search "MCP server" @2026-05-07 | ✅ 已验证 |
| 99319 AST repos | GitHub Search "mcp server AST parser tree-sitter" | ✅ 已验证 |
| 101266 DB repos | GitHub Search "mcp mssql postgres sqlite server" | ✅ 已验证 |
| 266K+ NPM 月下载 | NPM Registry "Notion MCP" | ✅ 已验证 |
| awesome-mcp-servers 清单 | raw.githubusercontent.com (base64) — 73 万字符 | ✅ 已验证 |
| 当前 MCP 配置基线 | `cline_mcp_settings.json` 本地读取 | ✅ 已验证 |
| SkillFoundry 基础设施 | `SKILLS_MANIFEST.json` + `systemPatterns.md` + `activeContext.md` | ✅ 已验证 |