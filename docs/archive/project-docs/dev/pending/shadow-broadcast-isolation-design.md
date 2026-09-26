# 待讨论: 影子广播机制 + 7天隔离期

**状态**: PENDING — 等待后续细化讨论  
**来源**: Phase C 信息流回审（原始讨论文档已丢失，需从对话记录重建）  
**创建日期**: 2026-05-17

## 待解决问题

1. **广播机制**: 主AI和影子如何同时收到原始新闻+Flash处理过的信息？信息流的分支节点在哪里？
2. **ELITE影子参与流程**: 主AI选出投资方向→查ELITE影子→通知用户→用户决定→主AI组织讨论
3. **7天隔离期**: ELITE影子参与讨论后，7天内仍可参与但不再接收主AI观点，防止锚定偏差累积
4. **Daredevil Elite 特例**: 达到Elite等级的敢死队影子每天均可考虑调用

## 相关文件

- `phase_b_ideation_notes.md` §1 — 影子 7 步分析工作流
- `phase_b_ideation_notes.md` §4 — ELITE Gate 2 参与
- `shadows/elite_participation.py` — EliteRegistry 实现
- `shadow_schema.py` — `post_collaboration_quarantine` 列 (migration 8)

## 下一步

重新讨论后写入权威设计文档，更新 pipeline 和 CLAUDE.md。
