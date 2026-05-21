@echo off
cd /d "%~dp0"
echo MarketMind v2.0 — Starting...
start "" http://localhost:8520
python api_server.py
pause
