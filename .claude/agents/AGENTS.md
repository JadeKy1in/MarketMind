# MarketMind Agent Team Configuration

## Team Members

| Agent | Model | File |
|-------|-------|------|
| Architect | Opus 1M | `.claude/agents/architect.md` |
| Quant Analyst | Sonnet 1M | `.claude/agents/quant-analyst.md` |
| Data Engineer | Sonnet 1M | `.claude/agents/data-engineer.md` |
| UI Engineer | Sonnet 1M | `.claude/agents/ui-engineer.md` |
| Builder | Sonnet 1M | `.claude/agents/builder.md` |
| Red Team | Haiku 1M | `.claude/agents/red-team.md` |

## Routing Rules

User says → Route to:

- "设计架构" / "design" / "how should this work" / "prompt engineering" → **Architect**
- "怎么分析" / "investment logic" / "reflexivity" / "causal chain" / "red blue" → **Quant Analyst**
- "数据" / "data pipeline" / "RSS" / "爬虫" / "API" / "token budget" → **Data Engineer**
- "界面" / "UI" / "GUI" / "交互" / "按钮" / "面板" / "进度条" → **UI Engineer**
- "写代码" / "implement" / "build" / "fix" / "wire" / "integrate" → **Builder**
- "检查" / "audit" / "review" / "verify" / "find problems" / "QA" → **Red Team**

## Working Order

For new features:
1. Architect defines design → hands off
2. Quant Analyst defines analysis rules → hands off
3. Data Engineer + UI Engineer work in parallel:
   - Data Engineer: sources, caching, degradation, token budget
   - UI Engineer: async bridge, panels, progress bars, session management
4. Builder implements both → hands off
5. Red Team audits → reports to Architect

For bug fixes:
1. Red Team identifies issue → reports to Architect
2. Architect decides: design change needed? → routes to appropriate agent

## Discipline Rules (From Past Failures)

1. Architect: NEVER touches .py files
2. Quant Analyst: NEVER touches .py files
3. Data Engineer: ONLY touches data pipeline code (.py files in data/ scope)
4. UI Engineer: ONLY touches GUI code (.py files in ui/ scope)
5. Builder: NEVER changes architecture without ARCHITECTURE_HANDOFF update
6. Red Team: READ-ONLY, find bugs but don't fix them
7. Builder: Every change verified with `python -c "import ast; ast.parse(open('file.py').read())"` before reporting done
8. ALL agents: never use the Edit tool on files >200 lines — use bash heredoc instead
