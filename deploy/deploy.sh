#!/usr/bin/env bash
# Smart deploy: only restarts backend when backend files actually changed.
# Run from /home/vs.bitcoding/gold-mcx-arbitrage AFTER `git fetch && git reset --hard origin/main`.
set -euo pipefail

APP_DIR="/home/vs.bitcoding/gold-mcx-arbitrage"
PREV_REF_FILE="/tmp/arbi-last-deploy-sha"

cd "$APP_DIR"
CURRENT=$(git rev-parse HEAD)
PREV=$(cat "$PREV_REF_FILE" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null || echo "")

if [ -n "$PREV" ] && [ "$PREV" != "$CURRENT" ]; then
    BACKEND_CHANGED=$(git diff --name-only "$PREV" "$CURRENT" -- backend/ | wc -l)
    FRONTEND_CHANGED=$(git diff --name-only "$PREV" "$CURRENT" -- frontend/ | wc -l)
    DEPS_CHANGED=$(git diff --name-only "$PREV" "$CURRENT" -- backend/requirements.txt | wc -l)
else
    BACKEND_CHANGED=1
    FRONTEND_CHANGED=1
    DEPS_CHANGED=1
fi

echo "==> Changes: backend=$BACKEND_CHANGED frontend=$FRONTEND_CHANGED deps=$DEPS_CHANGED"

if [ "$DEPS_CHANGED" -gt 0 ]; then
    echo "==> Reinstalling backend deps"
    cd "$APP_DIR/backend"
    ./venv/bin/pip install -r requirements.txt --quiet
fi

if [ "$FRONTEND_CHANGED" -gt 0 ]; then
    echo "==> Rebuilding frontend"
    cd "$APP_DIR/frontend"
    npm install --no-audit --no-fund --silent
    npm run build
    sudo rm -rf /var/www/arbitrage/assets
    sudo cp -a "$APP_DIR/frontend/dist/." /var/www/arbitrage/
    sudo chown -R www-data:www-data /var/www/arbitrage
    sudo find /var/www/arbitrage -type d -exec chmod 755 {} \;
    sudo find /var/www/arbitrage -type f -exec chmod 644 {} \;
    echo "==> Frontend live (no backend restart needed)"
fi

if [ "$BACKEND_CHANGED" -gt 0 ]; then
    echo "==> Backend changed → restarting service (brief feed downtime)"
    sudo systemctl restart arbi-backend.service
    sleep 4
    sudo systemctl is-active arbi-backend.service
else
    echo "==> Backend unchanged → keeping live feed connected"
fi

echo "$CURRENT" > "$PREV_REF_FILE"
echo "==> Deploy complete: $CURRENT"
