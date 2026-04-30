#!/usr/bin/env bash
# Pull latest code, install deps, build frontend, restart services.
# Run after setup.sh and after .env has been filled.
set -euo pipefail

DOMAIN="arbitrage.bitcoding.ai"
APP_DIR="/opt/arbi"
REPO="git@github.com:vsbitcoding/gold-mcx-arbitrage.git"

cd "$APP_DIR"
if [ ! -d ".git" ]; then
    echo "==> Cloning repo"
    git clone "$REPO" .
else
    echo "==> Pulling latest"
    git fetch origin
    git reset --hard origin/main
fi

echo "==> Backend venv + deps"
cd "$APP_DIR/backend"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

if [ ! -f ".env" ]; then
    echo "!! .env missing in $APP_DIR/backend — copy .env.example and fill credentials before continuing."
    cp .env.example .env
    echo "Edit /opt/arbi/backend/.env then re-run this script."
    exit 1
fi

echo "==> Frontend build"
cd "$APP_DIR/frontend"
npm install --no-audit --no-fund
npm run build

echo "==> Installing systemd unit"
sudo cp "$APP_DIR/deploy/systemd/arbi-backend.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable arbi-backend.service

echo "==> Installing nginx config"
sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/arbi.conf
sudo ln -sf /etc/nginx/sites-available/arbi.conf /etc/nginx/sites-enabled/arbi.conf
sudo rm -f /etc/nginx/sites-enabled/default

if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "==> Obtaining SSL cert (Certbot)"
    sudo certbot --nginx --non-interactive --agree-tos -m admin@bitcoding.ai -d "$DOMAIN" --redirect || true
fi

sudo nginx -t
sudo systemctl restart nginx
sudo systemctl restart arbi-backend.service

echo "==> Deploy complete. Visit https://$DOMAIN"
