# S5 设计：证据层 v1

> 规格来源：`docs/SPEC_v3.md` §9、§13（S5 验收：每日背离清单进入账本）。日期：2026-09-28。

## 范围

- **做**：5 类一手数据的取数；新闻 → 可检验说法 → 用一手数据核对 → 支持 / 矛盾 / 无法验证；每日背离清单写文件并进入统一账本；仪表盘"证据层"页。
- **不做**：把背离清单喂给主管线 L1 / 决策（记入积压，另行确认）；付费数据源；ETF 资金流（没有免费一手数据源，一律判"无法验证"）。

## 数据源（2026-09-28 本机实测均可访问，均不需要密钥）

| 类别 | 接口 | 用途 |
|---|---|---|
| SEC EDGAR XBRL | `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`；代码 → CIK 用 `www.sec.gov/files/company_tickers.json` | 最近一个季度营收同比 |
| SEC EDGAR 全文检索 | `efts.sec.gov/LATEST/search-index`（按 CIK） | 近 90 天 8-K / 10-Q / 10-K 中的财务红旗用语 |
| FINRA RegSHO | `cdn.finra.org/equity/regsho/daily/CNMSshvol<YYYYMMDD>.txt` | 每日卖空成交占比 |
| 空头持仓 | Nasdaq（已有 `gateway/nasdaq_derivs.py`） | 两期空头持仓变化 |
| 纽约联储 | `markets.newyorkfed.org/api/rates/secured/sofr/last/30.json` | 短端资金利率走势 |
| 国债拍卖 | FiscalData `auctions_query` | 最近 7 天拍卖的认购倍数，对比同期限前 6 次均值 |
| 稳定币 | DefiLlama `stablecoins.llama.fi/stablecoincharts/all` | 稳定币总供应 30 天变化 |

SEC 要求 User-Agent 带联系方式；请求串行，间隔 0.15 秒。

## 流程（`marketmind/evidence/`）

1. **抽取说法**（Flash，1 次调用）：取 60 条新闻（先挑提到营收、空头、回购利率、国债拍卖、稳定币、资金流、财务红旗等关键词的，再按优先级补足），要求模型只抽出能用上表数据核对的说法，每条给出：说法原文（中文一句）、来源新闻编号、类型、标的（公司类必填）、说法认定的方向（`up` / `down`）。输出经代码校验：类型不在白名单、新闻编号不存在、公司类没有标的的，一律丢弃。最多 15 条。
2. **核对**（纯代码）：每种类型一个核对函数，算出数据方向 `up` / `down` / `flat`：

   | 类型 | `up` 的含义 | 判定规则 |
   |---|---|---|
   | revenue_growth | 营收增长 | 最近季度营收同比 > +2% 为 up，< −2% 为 down，否则 flat |
   | short_interest | 空头持仓增加 | Nasdaq 最近两期变化 > +5% up，< −5% down |
   | short_selling_pressure | 卖空加剧 | FINRA 最近一日卖空占比比前 4 日均值高 10% 以上为 up，低 10% 以上为 down |
   | filing_red_flag | 公司有财务红旗 | 近 90 天有命中为 up；没有命中判"无法验证"（没查到不等于不存在） |
   | funding_rates | 短端利率上行 | SOFR 最新值比约 20 个交易日前高 5bp 以上为 up，低 5bp 以上为 down |
   | treasury_demand | 国债需求强 | 近 7 天拍卖认购倍数 / 同期限前 6 次均值，平均 > 1.03 为 up，< 0.97 为 down |
   | stablecoin_supply | 稳定币供应增加 | 30 天变化 > +1% up，< −1% down |
   | etf_flows | — | 一律"无法验证"（无免费一手源） |

   说法方向与数据方向一致 → **支持**；相反，或说法有方向而数据持平 → **矛盾**；取不到数据 → **无法验证**。
3. **独立来源**：说法引用的新闻按 `config/source_independence.py` 计独立来源数；同一集团的转载算一个。≥ 2 个独立来源的背离标为"高置信"。
4. **背离清单** = 判为"矛盾"的说法。

## 进账本（押"数据是对的，叙事是错的"）

- `source_type = "evidence"`，`source_id = "evidence:v1:<类型>"`，下一个开盘价入场，持有 10 个交易日，仓位 $100。
- 方向：数据方向有明确含义时按数据方向；数据持平时押说法的反方向。

  | 类型 | 标的 | 数据 up 时 |
  |---|---|---|
  | revenue_growth | 该公司 | 做多 |
  | short_interest / short_selling_pressure | 该公司 | 做空 |
  | funding_rates | TLT | 做空 |
  | treasury_demand | TLT | 做多 |
  | stablecoin_supply | BTC-USD | 做多 |

- 确信度：1 个独立来源 0.55，≥ 2 个 0.60。可证伪条件写明"持有期内按叙事方向走即判错"。
- 同一天同一类型 + 标的只记一条。宏观类（利率、国债、稳定币）用代理标的，层级记为 `linkage`。

## 输出

- `data/evidence/<日期>.json`：全部说法、判定、数据摘要、来源新闻、账本编号。
- 仪表盘 `/api/wb/evidence` 读最新一份。
- 每日运行：新闻抓完后与影子并行后台执行；也可单独运行 `python marketmind/app.py --mode evidence`。同一天已有报告则跳过。

## 验收

- 离线测试：每个核对函数、抽取校验、方向映射、独立来源计数、账本写入、同日跳过。
- 真实运行一次：生成当日报告，背离条目进入账本，仪表盘可见。
