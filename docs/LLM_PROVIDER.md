# 语言模型切换：Claude / DeepSeek

> 所有人决定（2026-09-28）：有 Claude Max 订阅期间先用 Claude；回国后不能用 Claude 时一键切回 DeepSeek。主管线（L1、L2、红队、决策、每日汇报）用 Opus，其余（新闻预处理、影子、证据层、事件归并、汇报员）用 Sonnet。

## 一键切换

```powershell
powershell -ExecutionPolicy Bypass -File marketmind\scripts\switch_llm.ps1 claude     # 先做一次测试调用，成功才切换
powershell -ExecutionPolicy Bypass -File marketmind\scripts\switch_llm.ps1 deepseek
powershell -ExecutionPolicy Bypass -File marketmind\scripts\switch_llm.ps1 status
```

切换写的是用户环境变量 `MARKETMIND_LLM`；自动运行下次启动时生效（包装脚本会从注册表补读）。手动运行需要新开终端。换模型：`MARKETMIND_CLAUDE_PRO_MODEL`（默认 `opus`）、`MARKETMIND_CLAUDE_FLASH_MODEL`（默认 `sonnet`）。

## 原理与限制

- Claude 走本机 Claude Code 的非交互模式 `claude -p`：这是订阅支持的用法，消耗 Max 套餐额度，不另收费。Anthropic API 和 Agent SDK 需要单独计费的 API 密钥，订阅不包含（官方文档，2026-09-28 查证：code.claude.com/docs/en/authentication.md、agent-sdk/quickstart.md）。
- 每次调用一个独立进程：关闭全部工具、不保存会话、不加载用户 / 项目设置和 MCP、在中性目录运行（不读任何 CLAUDE.md）；系统提示经临时文件传入，正文经标准输入传入（Windows 命令行长度限制）。并发上限 4（`MARKETMIND_CLAUDE_CONCURRENCY`）。
- **与所有人自己使用 Claude 共用额度**（5 小时窗口和每周上限）。每天约 40 次调用、35 万 token。
- **自动降级**：Claude 调用失败（未登录、额度用完、超时）时这一次改走 DeepSeek；同一次运行连续失败 3 次后，其余调用全部改走 DeepSeek，并发站内警报。子进程被外部中断（退出码 0xC000013A，例如运行开头电脑进出待机，2026-09-30 / 10-01 因此整天退回 DeepSeek）不算 Claude 失败：等 30 秒重试一次，重试仍被中断才计 1 次失败；子进程以 CREATE_NO_WINDOW 启动，不弹控制台窗口。DeepSeek 密钥必须保留。
- 登录过期：长期无人值守时，可运行 `claude setup-token` 生成长期令牌，设为用户环境变量 `CLAUDE_CODE_OAUTH_TOKEN`。
- 测试一律不调用 Claude（`tests/conftest.py` 把 `MARKETMIND_LLM` 固定为 deepseek）。
