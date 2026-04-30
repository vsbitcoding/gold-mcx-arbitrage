# Gold MCX Arbitrage

Real-time spread monitoring and paper-trading dashboard for MCX Gold/Silver pair trading.

## Features

- Live bid/ask feed via Dhan WebSocket
- 6 spread pairs (Petal-Guinea, Petal-Ten, Petal-Mini, Guinea-Ten, Guinea-Mini, Ten-Mini)
- Two-side trading (Decrease + Increase Premium) per pair
- Paper trading mode (fake orders for testing)
- Auto entry trigger + auto/manual square-off
- Three-table dashboard (Live Monitor / Active Positions / Trade History)

## Stack

- Backend: FastAPI (Python 3.12)
- Frontend: React + Vite
- Database: PostgreSQL
- Cache: Redis
- Reverse Proxy: Nginx + Let's Encrypt SSL
- Hosting: VPS at arbitrage.bitcoding.ai

## Setup

See `deploy/` for production setup.

For local dev, copy `.env.example` to `.env` and fill credentials.

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```
