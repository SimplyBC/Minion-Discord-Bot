# Hypixel Minion Timer Bot

Discord bot that tracks Hypixel SkyBlock minion fill times with multi-drop support and Super Compactor math.

## Features
- `/setup` dashboard (ephemeral) with live countdowns
- Create / Edit / Delete / Restart via buttons & modals
- DM or channel notifications when due
- Catch-up notifications after host sleep
- SQLite persistence
- Accurate multi-drop modeling (skeleton, spider, cow, chicken, etc.)
- Super Compactor reduces slot usage ×160 per drop
- Diamond Spreading toggle, Expander, Flycatchers, Crystal multipliers

## Quick Start (local)
```bash
pip install -r requirements.txt
export DISCORD_TOKEN=your_bot_token
python main.py