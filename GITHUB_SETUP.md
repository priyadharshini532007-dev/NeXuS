# Free hosting on GitHub Actions (no VPS, no laptop)

The workflow `.github/workflows/nexus.yml` listens to Telegram for ~50 minutes per run (replies are near-instant while
a run is active), runs queued tasks, saves its state - encrypted with your STATE_KEY - to a `state` branch, and then
starts the next run itself. Between runs there is a gap of a few minutes; messages sent then are answered by the next
run. An hourly schedule restarts the chain if it ever stops. Use a PUBLIC repository (free minutes are not metered there).

## One-time setup
1. github.com -> New repository -> public, no README (e.g. `nexus-agent`).
2. In PowerShell:
   ```powershell
   cd P:\NEXUS\nexus
   git init -b main
   git add .
   git status            # check: no .env, no .db files, no projects/ or out/ folders listed
   git commit -m "NEXUS agent"
   git remote add origin https://github.com/<you>/nexus-agent.git
   git push -u origin main
   ```
3. Repo -> Settings -> Secrets and variables -> Actions -> New repository secret. Add:
   - `TELEGRAM_BOT_TOKEN` - from BotFather
   - `TELEGRAM_CHAT_ID` - the number you saved earlier
   - `STATE_KEY` - any long random passphrase; make one with
     `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})`  (save it somewhere safe)
   - `ANTHROPIC_API_KEY` - optional (paid; enables /research and deep blueprints)
4. Actions tab -> enable workflows -> `nexus` -> Run workflow (first run; later runs are automatic).
5. Stop the Windows copies: `Stop-ScheduledTask "NEXUS bot"; Disable-ScheduledTask "NEXUS bot"; Disable-ScheduledTask "NEXUS daily"`
6. Turn the laptop off and send `/start`, `/status`, `/idea`, `/cyber` from the phone.

## Honest limits
- Not 24/7 instant: gaps of a few minutes happen between runs. If a run fails, the chain stops until the hourly
  schedule restarts it, and GitHub can delay scheduled runs by hours (observed on this repo). Start it by hand from the
  Actions tab (nexus -> Run workflow) if the bot is silent for long.
- GitHub may disable scheduled workflows after 60 days without repository activity; re-enable them in the Actions tab.
- GitHub's terms restrict using Actions for things unrelated to the repository's software project. A bot host may be
  treated as misuse; read GitHub's current Actions terms and accept that risk, or move to a VPS later (Docker files are ready).
- Never commit `.env`; secrets live only in GitHub Secrets. The state branch holds only an encrypted file.
