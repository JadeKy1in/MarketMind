# MarketMind Restart Guide — 2026-05-24 EOD

**Tests**: 2,039 pass, 0 fail, 0 skip | **CI**: green | **Branch**: master
**All pushed**: no | **frontload_required**: true
**Commits today**: 24

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。上次完成：通知系统 + 进化追踪面板 + UI 增强。测试 2,039 pass。

---

## 今日完成 (2026-05-24)

### 通知/告警系统
- AlertManager：去重/限流/升级/脱敏/持久化，WebSocket 实时推送
- Dashboard UI：铃铛 + 弹窗（ERROR 30s）+ 紧急横幅（CRITICAL）+ 滚动日志
- Gateway 埋点：5 个降级点（预算耗尽/JSON回退/断路器切换）
- 8 个 Pipeline Stage：@monitor 装饰器自动捕获异常/空返回/超时

### 进化追踪
- `/evolution` 独立页面：影子进化活跃度网格 + 管线指标卡
- 停滞检测：CUSUM + PSI + 线性趋势 → 综合活跃度分（绿/黄/红）
- ActivityMonitor：只在活跃度等级变化时通知一次

### 基础设施
- max_token 修复：13 个 Pro 调用解除限制
- 浏览器缓存修复：三层防缓存（Server + HTML meta + ETag）
- 文档清理：~130 过期文件删除（git 历史可恢复）
- User Proxy Agent 冷启动：6 条偏好种子

### UI 增强
- ▶ Run 按钮：Dashboard 一键启动 mock 管线分析
- 影子排名：25 影子全显示，前 5 绿色高亮，后 5 红色高亮
- 影子中文名 + 投资标的/策略描述
- 影子详情页中英双语 + 统一字体
- 进化活跃度：红=停滞·Stagnant，黄=关注·Watch，绿=活跃·Active

---

## 明天可以做的

| # | 任务 | 说明 |
|:--:|------|------|
| **1** | **你亲自测试 Dashboard** | `python api_server.py` → `localhost:8520`，点 ▶ Run，看通知铃铛、进化页面、影子卡片是否符合预期 |
| 2 | AEL 调参实验 | `scripts/ael_experiment.py` 已有 mock 结果，可对比月频 vs 双周频 |
| 3 | 影子知识管理器测试 | 确认影子学习闭环是否正常 |
| 4 | 管线实盘验证 | `python app.py --mode daily`（需要 API 预算） |

---

## 快速命令

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python api_server.py                    # Dashboard → http://localhost:8520
python app.py --mode daily --mock -v    # 模拟分析
python -m pytest tests/ -q -m "not slow" -p no:warnings  # 测试
```

## 新增 API 端点

| 端点 | 用途 |
|------|------|
| `GET /api/alerts` | 最近 50 条告警 |
| `GET /api/alerts/health` | AlertManager 健康状态 |
| `POST /api/pipeline/run` | 触发管线（`{mock: true}` 模拟模式） |
| `GET /evolution` | 进化追踪页面 |
| `GET /api/evolution/shadows` | 影子进化快照 |
| `GET /api/evolution/pipeline` | 管线进化历史 |
| `GET /api/evolution/stagnation` | 活跃度分数 |

## 新增模块

| 模块 | 用途 |
|------|------|
| `notification/` | AlertManager + @monitor + sanitizer |
| `evolution/` | 停滞检测 + 快照存储 + 活跃度监控 |
| `shadows/shadow_metadata.py` | 影子中英文名 + 策略描述 |
