#!/usr/bin/env bash
# Deploy on VPS. Run from /home/vs.bitcoding/gold-mcx-arbitrage after `git fetch && git reset --hard origin/main`.
# Touches only the arbitrage app files, nginx site config for arbitrage.bitcoding.ai, and arbi-backend systemd unit.
set -euo pipefail

APP_DIR="/home/vs.bitcoding/gold-mcx-arbitrage"

echo "==> Backend venv + Python deps"
cd "$APP_DIR/backend"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt --quiet

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "!! Created .env from template. Fill credentials in $APP_DIR/backend/.env then rerun."
    exit 1
fi

echo "==> Frontend build"
cd "$APP_DIR/frontend"
npm install --no-audit --no-fund --silent
npm run build

echo "==> Publish build to /var/www/arbitrage"
sudo mkdir -p /var/www/arbitrage
sudo rm -rf /var/www/arbitrage/assets
sudo cp -a "$APP_DIR/frontend/dist/." /var/www/arbitrage/
sudo chown -R www-data:www-data /var/www/arbitrage
sudo find /var/www/arbitrage -type d -exec chmod 755 {} \;
sudo find /var/www/arbitrage -type f -exec chmod 644 {} \;

echo "==> Install systemd unit (arbi-backend)"
sudo cp "$APP_DIR/deploy/systemd/arbi-backend.service" /etc/systemd/system/arbi-backend.service
sudo systemctl daemon-reload
sudo systemctl enable arbi-backend.service

echo "==> Install nginx config (arbitrage.bitcoding.ai only)"
sudo cp "$APP_DIR/deploy/nginx-arbitrage.conf" /etc/nginx/sites-available/arbitrage.bitcoding.ai.conf
sudo nginx -t

echo "==> Stop any old uvicorn on port 8000 (non-systemd)"
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1

echo "==> Restart services"
sudo systemctl restart arbi-backend.service
sudo systemctl reload nginx

sleep 2
echo "==> Health check"
curl -s http://127.0.0.1:8000/api/health || echo "backend not responding yet"

echo ""
echo "==> Done. Visit https://arbitrage.bitcoding.ai/"
