@echo off
rem Start one paper trading day of the 4-strategy bake-off (M1, week-1 plan).
rem Double-click in the morning (Dhan tokens expire every 24h — refresh the
rem token in agent\.env first, then run this). Window stays open for the day;
rem the feed goes to Telegram, the log to agent\logs\bakeoff-YYYYMMDD.log.

setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0vibe-trading\agent"
set PYTHONPATH=.
python -m src.intraday.bakeoff %*
echo.
echo Bake-off session ended (exit %errorlevel%).
pause
