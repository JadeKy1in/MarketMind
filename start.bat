@echo off
chcp 65001 >nul
title Claude Code — DeepSeek V4 Pro
cd /d "E:\AI_Studio_Workspace"

:: ============================================================
:: Pre-Session Validation (REQUIRED — validates plugins + config)
:: ============================================================
echo ============================================
echo   Pre-Session Validator
echo ============================================
python ".claude/hooks/pre_session.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Pre-session check failed.
    echo   Fix: python "E:\AI_Studio_Workspace\.claude\hooks\pre_session.py"
    echo   Recovery: python "E:\AI_Studio_Workspace\.claude\hooks\recover_config.py"
    pause
    exit /b 1
)
echo.

:: ============================================================
:: DeepSeek Anthropic API
:: ============================================================
set "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic"
set "ANTHROPIC_AUTH_TOKEN=%DEEPSEEK_API_KEY%"
set "ANTHROPIC_MODEL=deepseek-v4-pro[1m]"
set "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]"
set "ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]"
set "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash"
set "CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash"
set "CLAUDE_CODE_EFFORT_LEVEL=max"
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"

:: ============================================================
:: Agent Team + Tool Search (per CLAUDE.md root rules)
:: ============================================================
set "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1"
set "ENABLE_TOOL_SEARCH=true"

:: ============================================================
:: VPN Proxy
:: ============================================================
set "HTTP_PROXY=http://127.0.0.1:10808"
set "HTTPS_PROXY=http://127.0.0.1:10808"
set "NO_PROXY=localhost,127.0.0.1"

:: ============================================================
:: Check API Key
:: ============================================================
if "%DEEPSEEK_API_KEY%"=="" (
    echo [ERROR] DEEPSEEK_API_KEY is not set in system environment variables.
    echo   Run in ADMIN CMD: setx DEEPSEEK_API_KEY "sk-your-api-key-here"
    echo   Then restart this CMD window and run start.bat again.
    pause
    exit /b 1
)

echo ============================================
echo   Claude Code CLI
echo   Model : DeepSeek V4 Pro [1m] + Flash
echo   Teams : 8 agents (Architect, Builder, Red Team x2, ...)
echo   Skills: Superpowers / Mattpocock / Karpathy
echo   Proxy : 127.0.0.1:10808
echo   Project: MarketMind
echo ============================================
echo.

claude --effort max
