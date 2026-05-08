# 技术上下文

## 技术栈总览

| 类别 | 选用技术 | 版本约束 |
|---|---|---|
| 运行时 | Python | >= 3.11, < 3.13 |
| 行情数据 | yfinance | 最新稳定版 |
| 数据分析 | pandas + numpy | 最新稳定版 |
| 技术指标 | pandas-ta | 最新稳定版 |
| 宏观日历 | investpy 或 fredapi | 最新稳定版 |
| LLM 推理 | DeepSeek API | 唯一指定（无容灾多模型设计） |
| 数据存储 | SQLite3 | Python 内置 |
| 爬虫框架 | requests + BeautifulSoup4 | 最新稳定版 |
| 单元测试 | pytest | >= 7.0 |

## 开发环境要求

- 操作系统: Windows 11（当前环境）
- Python 环境管理: venv 或 conda
- 包管理: pip（严格使用 requirements.txt 锁定版本）
- IDE: VS Code（当前环境）
- 版本控制: git（沿用当前工作区）

## 依赖白名单（允许 import）

```
# 核心数据处理
pandas
numpy

# 金融数据
yfinance
pandas-ta

# 网络请求
requests
beautifulsoup4
lxml

# 系统工具
json (内置)
sqlite3 (内置)
pathlib (内置)
datetime (内置)
argparse (内置)
logging (内置)

# 测试
pytest
pytest-mock

# 开发辅助
python-dotenv
```

## 依赖黑名单（禁止 import）

以下库因违反物理隔离纪律或与系统定位冲突，严禁在任何运行期脚本中出现：

```
# 券商 API（违反物理隔离纪律）
robin_stocks
alpaca-trade-api
ib_insync
td-ameritrade-python-api
schwab-py

# 任何交易执行库
ccxt
backtrader (仅运行期禁止, 开发期回测可用)
zipline

# 任何 WebSocket 实时数据流
websocket-client
```

## 账号状态 JSON 模板（人工输入协议）

文件位置: `projects/robinhood/account_state.json`

```json
{
  "last_updated": "2026-05-04",
  "cash": 100000.00,
  "positions": [
    {
      "ticker": "NVDA",
      "shares": 10,
      "avg_cost": 950.00,
      "current_price": 980.00
    }
  ],
  "buying_power": 90000.00,
  "notes": "手动更新，与实际券商账户保持一致"
}
```

## DeepSeek API 配置

系统通过与 DeepSeek API 的 HTTP 通信获取 Pro 模型推理结果。不引入任何第三方 SDK 封装。

```python
# 配置示例
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-reasoner"  # 推理模型
```

## 输出格式规范

1. 所有控制台输出: ASCII-only 纯文本
2. 报告格式: Markdown（无扩展语法）
3. 禁止字符: Unicode emoji (U+1F300-U+1F9FF)、装饰性框线字符（【】★☆※→⇒等）
4. 代码注释: 仅使用 ASCII 字符，长注释使用英文
5. 日志: 使用 Python logging 模块的标准格式

## 测试数据规范

### 事件驱动数据集

- 数据集划分为多种宏观状态片段: 流动性枯竭期、熔断期、量化宽松期、高通胀期
- 测试数据中注入特定历史节点的新闻数据
- 考卷式测试: 系统在"盲测"条件下仅根据当天数据做出决策

### 空仓压力测试

- 测试数据中必须包含连续数月的"逻辑真空期"
- 系统必须在此区间内保持空仓（不产生买入信号）
- 如系统在真空期产生任何买入建议，测试判定为失败

### 惩罚机制

- 夏普比率惩罚: 系统重复测试同一段历史数据来优化规则时，收益置信度将被削减
- 隔离测试原则: 核心逻辑定型后，仅在绝对隔离的测试集上运行一次

## 安全红线

- 不可存储任何真实券商凭证或 API Token 于代码仓库
- 使用 `.env` 文件管理 DeepSeek API Key，并添加至 `.gitignore`
- 账户状态 JSON 文件不得包含敏感个人信息
- 日志中不得输出完整的 API 请求/响应体（避免泄露 API Key）