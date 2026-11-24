# Copies the files the server needs to your VPS over SSH. Usage:
#   powershell -File upload_to_vps.ps1 youruser@your.server.ip
# It never uploads .env, your database or generated files - secrets are typed on the server by vps_setup.sh.
param([Parameter(Mandatory = $true)][string]$Target)
$files = "nexus.py","cloud_bot.py","blueprint.py","blueprint_spec.md","plans.json","sources.json","template.html",
         "requirements.txt","Dockerfile","docker-compose.yml","vps_setup.sh","DEPLOY.md",".env.example"
$missing = $files | Where-Object { -not (Test-Path (Join-Path $PSScriptRoot $_)) }
if ($missing) { Write-Error "Missing: $missing"; exit 1 }
ssh $Target "mkdir -p ~/nexus"
foreach ($f in $files) { scp (Join-Path $PSScriptRoot $f) "${Target}:~/nexus/$f" }
Write-Host "Uploaded. Now run:  ssh $Target   then:  cd ~/nexus && bash vps_setup.sh"
