#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 22.04/24.04 VPS. Run as a sudo-capable user, from the uploaded nexus folder:
#   bash vps_setup.sh
# What it does: installs Docker, enables a firewall that only allows SSH (NEXUS needs no inbound ports),
# asks for your secrets (typed hidden, saved to .env with mode 600), then builds and starts the service.
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "Enabling firewall (SSH only)..."
sudo apt-get install -y ufw >/dev/null
sudo ufw allow OpenSSH >/dev/null
sudo ufw --force enable >/dev/null

if [ ! -f .env ]; then
  echo "Enter your secrets (input is hidden; they are stored only in .env on this server)."
  read -rsp "TELEGRAM_BOT_TOKEN: " TOK; echo
  read -rp  "TELEGRAM_CHAT_ID: " CID
  read -rsp "ANTHROPIC_API_KEY (optional, press Enter to skip): " AK; echo
  umask 177
  printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\nANTHROPIC_API_KEY=%s\nGITHUB_TOKEN=\n' "$TOK" "$CID" "$AK" > .env
fi
chmod 600 .env

# docker group membership only applies to new sessions, so use sudo here
sudo docker compose up -d --build
sleep 8
sudo docker compose logs --tail 20
echo
echo "Done. Look above for: NEXUS cloud service started"
echo "Then follow step 3 and 4 in DEPLOY.md (stop the Windows tasks; run the phone-only test)."
