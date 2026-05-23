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
| 1 | UI 优化 | Dashboard 使用体验——你自己用的时候觉得哪里不好 |
| 2 | 其他问题 | 你自己跑起来发现的问题 |
| 3 | L1 JSON 解析 | 真实 LLM 偶尔返回非 JSON，regex fallback 已增强但可再优化 |
| 4 | User Proxy Agent 实战 | 首次启用代理系统，走一遍冷启动引导 |
| 5 | A/B 测试 AEL | `scripts/ael_experiment.py` 已跑通，可以调参实验 |
