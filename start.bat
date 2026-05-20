@echo off
REM ============================================================
REM Lattice — dev launcher
REM Opens three terminals: backend, frontend, bot.
REM Bot terminal exits cleanly with a "phase 2G not yet" message
REM until phase 2G wires up discord.py.
REM ============================================================

start "Lattice Backend"  cmd /k "cd /d %~dp0backend && uv run uvicorn lattice.main:app --reload --port 8000"
start "Lattice Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
start "Lattice Bot"      cmd /k "cd /d %~dp0bot && uv run python -m lattice_bot.main"
