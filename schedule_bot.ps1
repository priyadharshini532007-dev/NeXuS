# Registers "NEXUS bot": starts the Telegram listener at logon, hidden, restarts if it crashes.
# Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as user environment variables (already set via setx).
$dir = $PSScriptRoot
$py = (Get-Command python).Source
# EncodedCommand avoids nested-quote problems; cmd handles the log redirect reliably.
$inner = "cmd /c `"cd /d `"$dir`" && `"$py`" nexus.py bot >> bot.log 2>&1`""
$enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
$a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -EncodedCommand $enc"
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
     -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName "NEXUS bot" -Action $a -Trigger $t -Settings $s -Force | Out-Null
Start-ScheduledTask -TaskName "NEXUS bot"
Write-Host "NEXUS bot registered and started. Log: $dir\bot.log"
