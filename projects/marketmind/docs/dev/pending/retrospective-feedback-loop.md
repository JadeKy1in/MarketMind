# 待实现: 复盘信息回流到每日分析

**状态**: PENDING — 等待主 AI 分析管道完成后实施  
**创建日期**: 2026-05-17

## 核心需求

主 AI 每天做分析前，需要读取过去积累的信息：

### 1. 长期跟进清单
- 上次分析中标记为"继续观察"的事件（如"ECB 可能在下次会议加息，等待措辞变化"）
- 置信度 0.4-0.7 之间、未达到操作阈值但值得追踪的假设
- 用户手动标记要跟进的方向

### 2. 最近结晶的经验
- MethodologyEvolver 产出的成功方法论
- CrystallizationEngine 晋升到 semantic memory 的洞察
- AEL（Automated Experience Learning）慢速层的月度复盘结论

### 3. 过去类似情境的对比
- 历史决策卡片的回溯——类似市场环境下的决策和结果
- 影子生态的历史表现数据（Phase 2 后可用）

## 实现方案（待细化）

```
每天 Session 开始时:

1. 加载: 上次归档的完整分析文档
         → data/archive/YYYY/MM/DD/analysis/03_investigation_detail.json

2. 查询: 标记为 "MONITOR" 的假设是否有更新
         → 对比今天的新数据和上次的置信度

3. 查询: 最近结晶的方法论
         → shadow_state.methodology_changes 表

4. 注入: 将上述信息注入 Pro 的 Pre-Act 规划阶段
         → investigation_loop._pre_act_planning() 增加 context 参数
```

## 对应的归档需求

主 AI 在生成简讯之前，需要先保存完整的分析文档（再压缩成 80-120 字简讯）：
- 文件: `data/archive/YYYY/MM/DD/analysis/03_investigation_detail.json`
- 内容: 所有假设的完整逻辑链、4 层验证结果、反对意见、置信度计算过程
- 后续: `03_layer1_narrative.json` 只保留简讯摘要

## 归档点

归档 Agent 完成后需要补充：Stage 3 HVR 调查结束后、Gate 1 简讯生成前，保存完整调查文档。
