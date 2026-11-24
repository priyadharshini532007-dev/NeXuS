# Registers a daily 07:30 task: fetch, rebuild menu, send Telegram digest.
# Run from the PERMANENT folder this project lives in. Set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID as user env vars first (optional).
$dir = $PSScriptRoot
$py = (Get-Command python).Source
$cmd = "cd '$dir'; & '$py' nexus.py run; & '$py' nexus.py digest"
$a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -Command `"$cmd`""
$t = New-ScheduledTaskTrigger -Daily -At 7:30am
# Laptop-friendly: run on battery, catch up if the PC was off at 07:30.
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "NEXUS daily" -Action $a -Trigger $t -Settings $s -Force
