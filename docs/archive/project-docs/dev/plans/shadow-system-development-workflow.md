# 影子系统开发流程 — 2026-05-19

**基于**: `shadow-ecosystem-full-design.md`（最终权威定义）
**状态**: 待用户审核 → 待红方审核

---

## 一、影子种类和定义（先审核）

以 `shadow-ecosystem-full-design.md` 为唯一基准，你逐类确认：

| 类别 | 数量 | 关键特征 | 确认？ |
|------|:---:|------|:---:|
| Expert | 15 | 领域锁定，4+/N指标确认，各自最大仓位 | ⬜ |
| Daredevil 主动型 | 5 | 每日必须决策，1-20天持仓 | ⬜ |
| Daredevil 环境型 | 2 | 震荡市/恐慌市触发 | ⬜ |
| Daredevil 做空 | 1 | 崩溃猎人 | ⬜ |
| Catfish | 机制 | 生态审计员，非影子 | ⬜ |
| Temp Event | 机制 | 里程碑记录器，30天，3-5次Pro | ⬜ |
| MissedPath | 机制 | 反事实追踪，只读不投票 | ⬜ |
| Challenger | 机制 | 秘密竞争者，3阶段淘汰 | ⬜ |
| Beta | 机制 | 量化调参+定性方法论测试 | ⬜ |

---

## 二、影子如何获取信息

```
主AI管道产出:
  Stage 1 Scout → news_items (345条，按tier排序)
  Stage 2 Flash → signals (事件类型、等级、方向)
  事件聚类 → 10-15个命名主题 + 跨簇因果链
  
影子接收（信息广播规则）:
  ✅ 原始新闻全文（news_items）
  ✅ 市场数据（价格、基本面）
  ✅ 用户Gate 1的原始意见和上传材料
  ❌ 主AI的L1/L2/L3分析报告（防锚定）
  ❌ 其他影子的分析输出（分析阶段内）
```

---

## 三、影子分析决策流程

```
每天7:00:
  1. 读取个人记忆（过去的成功、失败、教训）  ← 先从学习层读
  2. 读取原始新闻 + 市场数据                   ← 广播规则
  3. 预热分析（选方向、建假设）                ← 独立LLM调用
  4. 决策: 做多/做空/弃权 + 置信度             ← 结构化输出
  5. 消耗Flash配额查额外数据（可选）            ← 配额制
  6. 产出分析报告 → 存入shadow_analyses表      ← 归档
```

---

## 四、影子输出归档

```sql
-- shadow_analyses 表（每次分析一条）
shadow_id, date, ticker, direction, confidence, 
thesis, risk_note, methodology_version, tokens_consumed

-- shadow_rankings 表（每次排名一条）  
shadow_id, date, tier, composite_score, brier_score

-- entity_memories 表（Phase I，累积）
entity_id, avg_accuracy, recurring_patterns, key_levels, blind_spots
```

---

## 五、评价与评分

```
复合排名: C = 0.35×MPPM + 0.25×Calmar + 0.20×Omega + 0.20×WR
过拟合惩罚: × T/(T+8+24×ln(N))

Phase I 增强（数据积累后激活）:
  + Brier 分数（预测准确率）
  + 方向准确率
  + 校准误差（ECE）
  + 代币效率（收益/消耗token）

反躺平惩罚:
  - 126天未达ELITE → 停滞扣分
  - 胜率波动过小 → 稳定性扣分
  - 长期无洞察 → 干旱扣分
  - 过度持币 → 弃权扣分

胜率/盈利矩阵:
              盈利>0   盈利≈0   盈利<0
  胜率>线      🟢最佳    🟡及格    🔴最大扣分
  胜率<线      🟠存活    🟠双弱    🔴双倍扣分
```

---

## 六、晋级/降级/淘汰

```
晋级:
  专家: ≥120天 + ≥100笔 + 胜率>60% + Deflated Sharpe>0 + PBO<5% + MDD<25%
  敢死队: ≥60天 + ≥50笔 + 胜率>55% + Deflated Sharpe>0 + PBO<10% + MDD<35%
  必须穿越≥1次VIX>25高波动期
  必须在领域内跑赢主AI

降级:
  composite<p30 持续10天 → WATCH（配额5→3）
  composite<p15 持续20天 → ENDANGERED（配额5→1）
  WATCH→NORMAL: p≥p30连续5天
  ENDANGERED→WATCH: p≥p15连续10天

淘汰（三阶段缓冲）:
  Stage 1: 连续2期底部20% → 警告
  Stage 2: 连续3期底部20% → 观察+秘密挑战者
  Stage 3: 2周无改善 → 挑战者vs目标，胜者留下
  
重置:
  6个月未达EXCELLENT + 3个月胜率波动<±5% + 3个月无洞察
  → 全部满足即淘汰（每月最多2个）
```

---

## 七、复盘机制（接口留好）

```
复盘触发:
  预测发出时 → Phase I 记录 PredictableHypothesis
  预测到期时 → Phase I 验证 actual_outcome
  验证完成后 → Phase I reflection_agent 复盘

当前状态: Phase I 六层已全部建好，等数据积累

复盘接口（已就绪）:
  prediction_extractor.py  → 提取可验证预测
  calibration_tracker.py   → Brier评分+ECE
  reflection_agent.py      → 根因分类+教训提取
  entity_memory.py          → 按资产积累知识
  expertise_discovery.py   → 发现影子专长

主管道/影子读取经验（接口已就绪）:
  entity_memory.py → load_entity_memories() → 注入system prompt
```

---

## 八、可能遗漏 + 需要外网研究的

| 遗漏点 | 说明 |
|------|------|
| **影子启动时机** | 主AI Stage 4 启动同时？Stage 1 完成后立即启动？ |
| **影子间通信协议** | 7天隔离期内影子不能互看——通过什么机制在隔离期后交换信息？ |
| **方法论版本控制** | 影子方法论升级后，旧版本保留多久？怎么和旧版本对比？ |
| **影子命名和标识** | 用户如何在Gate 2提到特定影子？显示名称唯一吗？ |
| **临时影子资本来源** | Temp Event从哪拿虚拟资本？固定额度还是从主池分配？ |
| **Beta影子晋升路径** | Beta→正式影子需要什么条件？谁审批？ |
| **生态审计员的权限** | 猫鱼v2检测到盲点后——只报告还是能干预影子配额？ |
| **Flash配额跨日结算** | 影子今天配额没用完——顺延到明天还是清零？ |
| **多资产同时分析** | 一个影子同一天能做多笔相互独立的交易吗？ |
| **复盘触发时机** | 复盘是每天固定时间跑一次？还是每个预测到期即时触发？ |

---

## 九、明天开发顺序

```
1. 影子种类和定义 → 你逐类确认
2. 影子和主管道信息流设计 → 我画数据流图
3. 方法调用: superpowers:brainstorming + mattpocock:grill-me → 推演逻辑漏洞
4. 红方审核完整方案
5. 代码实施（基于今天清理后的 shadows/ 基线）
6. PICA + 端到端测试
```
