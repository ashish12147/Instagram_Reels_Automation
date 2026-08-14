# Instagram Reels Automation — Railway + Telegram

Advanced, script-only Instagram Reel automation for Railway. No Hermes and no LLM are required at runtime.

## Features

- Posts 4 Reels/day by default at 09:30, 13:30, 17:30 and 21:30 IST
- Pulls Reels from the configured public Google Drive folder
- Natural numeric ordering and persistent SQLite duplicate protection
- Deterministic rotating captions
- Instagram resumable upload + publish flow
- Owner-only Telegram control panel
- `/panel`, `/status`, `/next`, `/stats`, `/queue`, `/refresh`, `/history`, `/errors`, `/dryrun`, `/postnow`, `/pause`, `/resume`, `/schedule`, `/skipnext`, `/retry`, `/report`, `/health`
- Success/failure reports after posting attempts
- Daily report at 22:15 IST by default
- Railway `/health` endpoint

## Required Railway variables

- `DRIVE_FOLDER_ID`
- `INSTAGRAM_USER_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Do not commit token values to this repository.

## Persistent volume

Attach a Railway Volume at `/opt/data`. The app automatically uses `RAILWAY_VOLUME_MOUNT_PATH` when Railway provides it. Posting history, duplicate state, schedule changes and control state survive redeployments on that volume.

## Deployment

1. Deploy this repository to Railway.
2. Add the required variables.
3. Attach a volume at `/opt/data`.
4. Deploy.
5. In Telegram send `/panel`, then `/dryrun`.
6. Confirm the correct next Reel before allowing live posting.

The repository stores the two larger Python source files in `source_parts/`. `bootstrap.py` reconstructs them byte-for-byte at startup and verifies SHA-256 checksums before execution. This packaging is only for repository transport; runtime behavior is the same as the validated source.

## Default schedule

`09:30,13:30,17:30,21:30` in `Asia/Kolkata`. Change it live from Telegram with:

`/schedule 09:30 13:30 17:30 21:30`

## Important Telegram note

If an old Hermes process is still using the same Telegram bot token, stop that Telegram consumer first. This service owns the bot's long-polling updates.
