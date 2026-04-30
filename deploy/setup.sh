#!/usr/bin/env bash
# One-time server setup. Run as a sudoer user.
# Usage: bash setup.sh
set -euo pipefail

DOMAIN="arbitrage.bitcoding.ai"
APP_DIR="/opt/arbi"
SVC_USER="vs.bitcoding"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3.12 python3.12-venv python3-pip \
    postgresql postgresql-contrib redis-server nginx certbot \
    python3-certbot-nginx git curl build-essential libpq-dev

echo "==> Installing Node.js 20"
if ! command -v node >/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

echo "==> Creating Postgres DB + user"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='arbi'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER arbi WITH PASSWORD 'arbi_pass';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='arbi'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE arbi OWNER arbi;"

echo "==> Creating app directories"
sudo mkdir -p "$APP_DIR" /var/log/arbi
sudo chown -R "$SVC_USER:$SVC_USER" "$APP_DIR" /var/log/arbi

echo "==> Done. Now run deploy.sh to pull code + start services."
