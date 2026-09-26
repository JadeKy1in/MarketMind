# MarketMind

> AI 人机协作投研工作站 · 影子基金经理竞技场 · 白箱
> 个人项目。系统不替你交易，最终决策与下单由人在 Robinhood 手动完成。

**当前状态（2026-09-27）**：正在按 v3 规格重建（分支 `v3`）。旧版本在 14 次试运行中给出 0 次交易建议，影子只跑过 3 天且从未被打分。原因分析见 `docs/PROJECT_REVIEW_2026-09-27.md`。

## 它要做什么

- 每天在后台用多源信息和权威一手数据分析市场，识别"叙事与数据的背离"。
- 约 32 个彼此独立、以盈利为目标的影子（虚拟基金经理）每天被迫做虚拟投资；所有预测进入**统一账本**，到期后按真实价格结算，优胜劣汰。
- 只有在出现大行情时才发警报；你的实盘持仓每天巡检（离场、持有还是换标的）。
- 仪表盘和内置汇报员让系统始终是白箱。

详细内容见 **[docs/SPEC_v3.md](docs/SPEC_v3.md)**，这是唯一事实来源。

## 目录

```
marketmind/        Python 包（管线、影子、网关、API、仪表盘页面、测试）
  pipeline/  shadows/  gateway/  api/  config/  playground/  storage/
  integrity/ notification/ evolution/ ui/  tools/  scripts/  tests/
docs/
  SPEC_v3.md                    v3 产品与架构规格
  PROJECT_REVIEW_2026-09-27.md  全量文档评审与冲突清单
  archive/                      被取代的历史文档（只读参考）
```

## 运行

```bash
pip install -r requirements.txt

# 测试（在仓库根目录执行）
python -m pytest marketmind/tests -q -p no:warnings

# 仪表盘
python marketmind/api_server.py        # http://localhost:8520

# 每日管线（mock 模式，不调用 API）
python marketmind/app.py --mode daily --mock -v
```

需要的环境变量（真实运行时）：`DEEPSEEK_API_KEY`；可选 `FINNHUB_KEY`、`FRED_API_KEY`、`EIA_API_KEY`。不要把真实密钥提交到仓库。
