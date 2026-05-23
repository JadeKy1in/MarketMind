# MarketMind Restart Guide — 2026-05-23 EOD

**Tests**: 1,998 pass, 0 fail, 0 skip | **CI**: green | **Branch**: master
**frontload_required**: true

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。

---

## ⚡ FRONTLOAD — 先交互再开发

1. Flash 扫描此文件 → 列出需要用户决定的点
2. 完成所有同步交互 → 然后启动异步 Agent

---

## 项目当前状态

### 已完成
- 10 pipeline stages + 3 gates（全管线实盘验证通过）
- Shadow ecosystem：25 shadows，ELITE，challenger
- API server + WebSocket + Dashboard（影子详情页）
- 模块化：所有文件 <550 行，6 个 L1 模块，7 个 grandfather 新模块
- 测试：1,998 pass，覆盖率全面
- CI/CD：GitHub Actions，push 自动跑
- 门禁：PreToolUse start gate + 7-gate Stop gate（PICA 自动刷新）
- User Proxy Agent v1.1（19 红方发现修复）
- 代码清理：461 死文件删除，worktree 自动清理

### 运行时快速命令
```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python api_server.py                    # Dashboard → http://localhost:8520
python app.py --mode daily --mock -v    # 模拟分析（不花钱）
python app.py --mode daily -v           # 真实 API 分析
python -m pytest tests/ -v -m "not slow" -p no:warnings  # 快速测试
```

---

## 下次可以做的

| # | 任务 | 说明 |
|:--:|------|------|
| **1** | **通知/报错系统** | 最高优先级——所有降级、fallback、异常必须通过 Dashboard 通知用户。包括：思考溢出(content空)、JSON回退、float解析失败、API错误、预算耗尽。需设计统一的 AlertManager + Dashboard 通知面板 |
| 2 | UI 优化 | Dashboard 使用体验——你自己用的时候觉得哪里不好 |
| 3 | User Proxy Agent 实战 | 首次启用代理系统，走一遍冷启动引导 |
| 4 | A/B 测试 AEL | `scripts/ael_experiment.py` 已跑通，可以调参实验 |

## 最近修复

- **LLM JSON 可靠性**: 思考模式 token 竞争修复——max_tokens 从 4K→32K(Pro默认)、_extract_json_from_reasoning 兜底
- **全量审计**: 20 问题修完（8 HIGH + 5 MED + 7 LOW）
- **一致性检查**: Stop hook 每次会话结束自动扫描
