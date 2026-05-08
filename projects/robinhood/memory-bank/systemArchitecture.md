# 系统架构

## 整体架构概览

SystemArchitecture 采用模块化分层设计，分为 4 个独立的分析层 + 1 个输出层。每层之间通过纯 JSON 结构化契约进行通信，确保单层替换不影响其他层工作。

```
 +-------------------------------------------------------------+
 |                   用户触发（CLI 脚本入口）                      |
 +-------------------------------------------------------------+
                              |
                              v
 +-------------------------------------------------------------+
 |  Layer 1: 数据采集模块 (Data Ingestion)                       |
 |  - 本地 JSON 账户状态读取器                                    |
 |  - 市场行情采集器 (yfinance 周线 + 日线)                       |
 |  - 宏观事件日历采集器 (公开经济数据 API)                        |
 |  - KOL/政要发言采集管道 (Truth Social / RSS / 公开数据源)       |
 |  - 国会议员交易披露解析器 (公开数据源)                           |
 +-------------------------------------------------------------+
                              |
                    (结构化 JSON 数据包)
                              v
 +-------------------------------------------------------------+
 |  Layer 2: 四维分析引擎 (4D Resonance Engine)                  |
 |  +----------------+  +----------------+  +----------------+  |
 |  | 基本面分析引擎    |  | 技术分析引擎    |  | 事件驱动引擎    |  |
 |  | (宏观周期推演    |  | (周线多时间框架 |  | (地缘政治蝴蝶   |  |
 |  |  产业链逻辑链)   |  |  MACD 背离检测) |  |  效应多级推演)  |  |
 |  +----------------+  +----------------+  +----------------+  |
 |  +----------------+                                          |
 |  | 情绪解码引擎    |  (DeepSeek API 处理非结构化文本)           |
 |  | (KOL/政要发言   |                                          |
 |  |  LLM 结构化提取) |                                          |
 |  +----------------+                                          |
 +-------------------------------------------------------------+
                              |
           (各维度独立打分: 0-100, 附带推演逻辑文本)
                              v
 +-------------------------------------------------------------+
 |  Layer 3: 决策汇总模块 (Decision Aggregator)                  |
 |  - 四维共振打分器: 汇总 4 个引擎的分数                        |
 |  - 逻辑链完整性校验: 检查 >=3/4 维度是否共振                  |
 |  - 资金管理模块: 读取本地 JSON 账户状态                       |
 |  - DeepSeek Pro 模式深度推演                                   |
 +-------------------------------------------------------------+
                              |
                    (结构化决策报告 JSON)
                              v
 +-------------------------------------------------------------+
 |  Layer 4: 输出层 (Output Formatter)                           |
 |  - 纯文本 Markdown 报告生成 (禁止 emoji / 装饰符)              |
 |  - 三个标准板块:                                              |
 |    (1) 当前持仓处置建议                                        |
 |    (2) 宏观与逻辑推演深度分析 (叙事性散文体)                    |
 |    (3) 最终行动指令 (Ticker / 方向 / 时间线 / 仓位)            |
 +-------------------------------------------------------------+
```

## 三大系统天条的架构固化

### 天条 1: UI/输出纪律 - 固化在输出层

- 输出层设计约束: 所有输出格式为 ASCII-only 纯文本 Markdown
- 禁止所有 Unicode emoji、花哨装饰字符
- 代码注释规范: 仅使用 ASCII 字符，禁止【】等装饰性符号
- 写入 `output_formatter.py` 中的硬校验: 检测输出中是否含非 ASCII 装饰字符

### 天条 2: 物理隔离纪律 - 固化在系统边界

- 系统边界图: 数据采集层与任何券商 API 之间有一条不可逾越的红线
- 数据采集层中不存在任何 `robin_stocks`、`alpaca-trade-api`、`ib_insync` 等交易执行库
- 唯一的"账户状态"入口是 Layer 1 中的 **本地 JSON 文件读取器**
- 资金管理系统只读取 `account_state.json` 文件，不做任何写回交易所操作
- 写入 `config.py` 中的依赖白名单/黑名单

### 天条 3: 反拟合纪律 - 固化在决策引擎

- Layer 3 的共振逻辑: 价格序列数据（由技术分析引擎处理）仅作为"时机过滤"
- 信号生成的必要条件: 必须经过基本面/事件/情绪的逻辑链硬过滤
- 测试套件中强制包含: 空仓压力测试（系统在逻辑真空期不作开仓）
- 不允许多参数暴力穷举优化

## 模块间通信协议

所有模块间的数据交换遵循统一的 JSON Schema:

```typescript
// 数据采集模块输出 -> 分析引擎输入
interface IngestionOutput {
  market_data: {
    [ticker: string]: {
      daily: Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>;
      weekly: Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>;
    };
  };
  macro_events: Array<{
    date: string;
    title: string;
    description: string;
    category: "economic" | "geopolitical" | "policy" | "earnings";
  }>;
  sentiment_data: Array<{
    source: string;
    author: string;
    text: string;
    mentioned_tickers: string[];
    timestamp: string;
  }>;
  account_state: {
    cash: number;
    positions: Array<{ ticker: string; shares: number; avg_cost: number }>;
    buying_power: number;
  };
}

// 分析引擎输出 -> 决策汇总模块输入
interface EngineOutput {
  fundamental: { score: number; reasoning: string };
  technical: { score: number; reasoning: string };
  event_driven: { score: number; reasoning: string };
  sentiment: { score: number; reasoning: string };
}
```

## 开发阶段的工具链

沿用 SkillFoundry 的工程范式:
- TypeScript 工具链用于开发阶段的自动化脚本和测试
- `.clinerules` 纪律体系管辖开发行为
- Memory Bank 协议用于跨 Session 记忆同步
- 最终产物为纯 Python 轻量级命令行工具

## 核心依赖架构

```
开发期工具: 沿用现有 infrastructure/skills/
运行期产物: 纯 Python 脚本（无 TypeScript 依赖）
LLM 后端: DeepSeek API（唯一指定，无多模型容灾设计）
数据源: 公开免费的金融数据 API（yfinance 等）
账户状态: 本地人工维护的 JSON 文件
数据存储: 本地 SQLite（可选）