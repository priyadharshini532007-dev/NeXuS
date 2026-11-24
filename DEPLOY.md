# Deploying NEXUS to the cloud (laptop-independent)

`cloud_bot.py` is the production service. It long-polls Telegram, stores every update and task in SQLite (on a volume),
acknowledges each command with a task ID, runs it in background workers, and ends every task in a result or an explicit
failure message. It also fetches news every 6 h and sends the daily digest. Nothing needs your laptop.

## 1. Pick a host (your decision, may cost money)
You need an always-on machine that can run Docker and keep a disk between restarts. Options: a small VPS from any provider,
or a container platform with a persistent volume. Before choosing, check the provider's *current* pricing, whether the
instance sleeps when idle (it must not), and whether the volume survives redeploys. I have not verified any provider.
Telegram's API must be reachable from the host (it is blocked on some home networks, not usually on cloud hosts).

## 2. Deploy (on the host)
```bash
git clone <your repo> nexus && cd nexus        # or copy the folder
cp .env.example .env && nano .env              # paste TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (never commit .env)
docker compose up -d --build
docker compose logs -f                         # look for: NEXUS cloud service started
```
Restart policy is `unless-stopped`; the container healthcheck fails if the poll loop stops.

## 3. Switch off the laptop copies (only one poller may run per bot)
On Windows: `Stop-ScheduledTask "NEXUS bot"; Disable-ScheduledTask "NEXUS bot"` and the same for `"NEXUS daily"`.

## 4. Phone-only acceptance test (do this yourself; it is not verified yet)
1. Shut the laptop down completely.
2. On the phone send `/start`, `/help`, `/status` -> each must reply; `/status` shows real checks.
3. `/idea` and `/cyber` -> immediate "received, Task ID NX-xxx", then the result.
4. Send an invalid command and `/idea` + `/cyber` + `/status` quickly -> separate acknowledgements.
5. `docker compose restart` -> `/status` still works; `/result NX-001` resends an old result.
6. Optional: remove ANTHROPIC_API_KEY and send `/research x` -> it must say "Not configured", not stay silent.

## Known limits
- Long polling, not a webhook (accepted by the spec; no public HTTPS needed).
- `/research` and `/deepdive` use model knowledge only (no live web search) and need ANTHROPIC_API_KEY.
- `/validate` is a checklist, not a patent/paper search.
- Delivery is retried 3 times; if it still fails the result stays stored and `/result NX-id` resends it.
- No offsite database backup yet: snapshot the `nexus-data` volume.
