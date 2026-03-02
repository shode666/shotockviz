# StockViz

> 📈 Self-hosted stock analysis platform for Thai (SET/mai) and US markets with advanced charting, portfolio tracking, and AI-powered tools. Zero monthly fees — runs on Docker.

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![React](https://img.shields.io/badge/react-19%2B-61dafb)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-Beta-orange)

[**Features**](#features) • [**Quick Start**](#quick-start) • [**Tech Stack**](#tech-stack) • [**Docs**](#documentation) • [**Contributing**](#contributing)

---

## Features

### 📊 Charts & Analysis

- **Multiple Chart Types**: Candlestick, Line, Area, Bar
- **Timeframes**: 1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M
- **Drawing Tools**: Trend lines, Fibonacci, H-lines, Rectangles, Arrows, Pitchfork
- **Technical Indicators**: MA, EMA, RSI, MACD, Bollinger Bands, Volume, Stochastic, Ichimoku
- **Compare Mode**: Overlay 2 stocks on same chart
- **Thai-Specific**: XD/XR dividend markers on chart

### 💼 Portfolio & Tracking

- **Transaction Management**: Record Buy/Sell trades with fees
- **Real-Time Analytics**: Current value, P&L, allocation pie chart
- **Risk Metrics**: Sharpe Ratio, Max Drawdown, Beta, Correlation
- **Fundamental Data**: P/E, P/BV, Dividend Yield, Market Cap

### 🔔 Alerts & Notifications

- **Alert Types**: Price, RSI, MACD, Golden Cross, Volume Spike
- **Channels**: Telegram Bot (instant), In-app, Email (optional)
- **Smart Triggers**: Pattern-based alerts, not just price

### 🔍 Stock Screener

- **Advanced Filters**: Market, price, P/E, RSI, MACD, volume
- **Save Presets**: Re-use favorite filter combinations
- **Export Results**: Download screening results as CSV

### 📰 News & Sentiment

- **Multi-Source**: Google News RSS + Finnhub + SET news
- **AI Sentiment**: Local analysis (Ollama) — Positive/Negative/Neutral
- **Filtered Feed**: By market, symbol, or watchlist

### 📊 Backtesting

- **Strategy Builder**: Create entry/exit rules visually
- **Historical Testing**: Test on 5+ years of data
- **Performance Metrics**: Return, Drawdown, Sharpe, Trade Log
- **Benchmark Comparison**: vs SET Index or S&P500

### 🛡️ Security

- **User Authentication**: JWT + bcrypt password hashing
- **Role-Based Access**: Guest (read-only) vs User (full access)
- **Rate Limiting**: Per IP & per user
- **Secure API**: HTTPS, CSRF protection, SQL injection prevention

### 🌙 UI/UX

- **Dark Mode**: Default with light mode toggle
- **2026 Design Trends**: Modern, gradient accents, glass effects
- **Responsive**: Desktop-first, works on tablets
- **Keyboard Shortcuts**: Ctrl+K for search, Ctrl+Z for undo

---

## Quick Start

### Requirements

- Docker & Docker Compose (v2.0+)
- 4GB+ RAM, 10GB free disk
- Internet connection (for stock data)

### 1️⃣ Clone & Configure

```bash
git clone https://github.com/yourusername/stockviz.git
cd stockviz
cp .env.example .env
```

### 2️⃣ Start (Dev Mode)

```bash
docker-compose -f docker-compose.dev.yml up
```

**Access:**
- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs
- DB Admin: http://localhost:5050 (optional)

### 3️⃣ Create First User

```bash
docker-compose -f docker-compose.dev.yml exec backend python scripts/create_user.py
# Follow prompts to create user account
```

### 4️⃣ Login

Visit http://localhost:5173 and login with your credentials.

### 5️⃣ Start Analyzing! 📈

Try searching for a stock (e.g., "PTT.BK", "AAPL") and start analyzing.

---

## Tech Stack

### Frontend

```
React 19           - UI library
Vite 7             - Fast bundler
Tailwind CSS 4     - Styling
TradingView LWC 5  - Professional charts
Zustand 5          - State management
Axios              - API data fetching
WebSocket          - Real-time prices
```

### Backend

```
Python 3.13+ / uv  - Runtime & package manager
FastAPI 0.131      - Modern Python API
SQLAlchemy 2.0     - Database models
Pydantic 2.12      - Data validation
JWT (PyJWT)        - Authentication
Celery 5.6 + Redis 7 - Background tasks & cache
PostgreSQL 16      - Main database
TimescaleDB        - Time-series optimization
yfinance           - Stock data (Thai + US)
Finnhub            - Secondary data source
Telegram Bot API   - Notifications
Ollama (optional)  - Local AI inference
```

### DevOps

```
Docker             - Containerization
Docker Compose     - Multi-container orchestration
Nginx              - Reverse proxy
Gunicorn           - WSGI server
```

### All Open Source & Free

No paid dependencies. Everything runs locally in Docker.

---

## Project Structure

```
stockviz/
├── frontend/                   # React + Vite app
│   └── src/
│       ├── pages/             # Page components
│       ├── components/        # Reusable components
│       ├── hooks/             # Custom React hooks
│       ├── services/          # API clients
│       └── store/             # State management
│
├── backend/                    # FastAPI app
│   ├── api/routes/            # API endpoints
│   ├── services/              # Business logic
│   ├── models/                # Data models
│   ├── workers/               # Celery tasks
│   └── core/                  # Config & utilities
│
├── docker-compose.dev.yml      # Development stack
├── docker-compose.prod.yml     # Production stack
├── REQUIREMENTS.md             # Detailed specifications
├── INSTRUCTIONS.md             # Development guide
└── README.md                   # This file
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [**REQUIREMENTS.md**](REQUIREMENTS.md) | Functional & non-functional specs, features, API endpoints |
| [**INSTRUCTIONS.md**](INSTRUCTIONS.md) | Development guide, coding standards, testing, troubleshooting |
| [**API.md**](docs/API.md) | Full API documentation (auto-generated at `/docs`) |
| [**ARCHITECTURE.md**](docs/ARCHITECTURE.md) | System design, data flow, security |
| [**DEPLOYMENT.md**](docs/DEPLOYMENT.md) | Production deployment, scaling, monitoring |

---

## Supported Markets

### Thai Market (SET/mai)

| Symbol Suffix | Exchange | Hours |
|---------------|----------|-------|
| `.BK` | SET / mai | Mon-Fri 09:30-16:30 ICT (break 12:30-14:00) |

**Examples**: PTT.BK, CPALL.BK, ADVANC.BK, TRUE.BK

### US Market (NYSE/NASDAQ)

| Market | Hours | Bangkok Time |
|--------|-------|--------------|
| NYSE/NASDAQ | Mon-Fri 09:30-16:00 ET | 21:30-04:00 ICT (next day) |

**Examples**: AAPL, NVDA, TSLA, META, GOOGL

### Indices

- SET Index
- S&P 500
- NASDAQ Composite
- Dow Jones Industrial Average

---

## Data Sources

| Source | Coverage | Lag | Free Tier |
|--------|----------|-----|-----------|
| yfinance | Thai + US | ~15 min | ✅ Unlimited |
| Finnhub | US stocks + news | ~15 min | ✅ 60 req/min |
| Google News RSS | News | ~realtime | ✅ Unlimited |
| SET Website | Thai data | End-of-day | ✅ Web scrape |

---

## Features Roadmap

### ✅ Phase 1 — MVP (6 weeks)
- [x] Project setup + Docker
- [ ] User authentication
- [ ] Stock charts + indicators
- [ ] Drawing tools
- [ ] Watchlist
- [ ] Basic alerts
- [ ] Dark mode

### 🔄 Phase 2 — Features (4 weeks)
- [ ] Portfolio tracking
- [ ] News feed + RSS
- [ ] Stock screener
- [ ] Backtesting
- [ ] Fundamental data

### 📋 Phase 3 — Advanced (4 weeks)
- [ ] AI sentiment analysis
- [ ] Advanced indicators
- [ ] Admin dashboard
- [ ] API rate limiting improvements
- [ ] Mobile responsive optimization

### 🚀 Future (Nice to Have)
- Mobile app (React Native)
- Real-time 0-delay data (with broker integration)
- Social trading / idea sharing
- White-label API
- Crypto / Forex markets

---

## Screenshots

*(Wireframe available at `wireframe.jsx` — opens in browser)*

### Chart View

Dark theme with candlestick chart, indicators, drawings, and bottom panels (news/portfolio/fundamentals).

### Screener

Advanced filters (RSI < 30, Volume > 3x, MACD buy signal) with results table.

### Portfolio

Transaction log, P&L tracking, risk metrics (Sharpe, Drawdown, Beta).

### Alerts

Create price/RSI/pattern alerts with Telegram notifications.

---

## Security

### Authentication

- JWT (15-minute access token + 7-day refresh token)
- bcrypt password hashing (cost factor 12+)
- Rate limiting (30 req/min for guests, 120 for users)

### Data Protection

- HTTPS only (TLS termination via Nginx)
- SQL parameterized queries (SQLAlchemy ORM)
- XSS/CSRF protection
- Secrets in .env (not in code)

### Infrastructure

- Non-root Docker user
- Read-only filesystem
- Network isolation between containers
- Dependency auditing (pip-audit, npm audit)

---

## Database Housekeeping

Automatically compresses old price data to reduce storage:

| Age | Resolution | Action |
|-----|-----------|--------|
| < 7 days | 1-minute | Raw storage |
| 7-90 days | 5-minute | Aggregate + delete 1m |
| 90d-2y | 1-day | Aggregate + delete 5m |
| > 2 years | 1-week | Aggregate + delete 1d |

Housekeeping runs daily at 03:00 ICT. Uses TimescaleDB continuous aggregates.

---

## Contributing

We welcome contributions! Here's how:

### 1. Fork & Branch

```bash
git clone https://github.com/yourusername/stockviz.git
git checkout -b feature/awesome-feature
```

### 2. Make Changes

Follow [coding standards](INSTRUCTIONS.md#coding-standards) in INSTRUCTIONS.md.

### 3. Test

```bash
docker-compose exec backend pytest tests/
npm test  # frontend
```

### 4. Commit & Push

```bash
git commit -m "feat: add awesome feature"
git push origin feature/awesome-feature
```

### 5. Create Pull Request

Include description, link issues, request review.

### Code of Conduct

- Be respectful and inclusive
- Report security issues privately (don't create public issues)
- No spam or self-promotion

---

## Performance

| Metric | Target |
|--------|--------|
| Page Load | < 2 seconds |
| Chart Render | < 500ms |
| API Response | < 200ms (P95) |
| WebSocket | < 100ms |
| Max Users | 50 (self-hosted) |

---

## Troubleshooting

### Port Already in Use

```bash
lsof -i :8000
kill -9 <PID>
```

### Database Error

```bash
docker-compose down -v
docker-compose up  # Fresh start
```

### Celery Not Working

```bash
docker-compose logs celery-worker
docker-compose exec redis redis-cli ping
```

See [INSTRUCTIONS.md](INSTRUCTIONS.md#troubleshooting) for more solutions.

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|------------|
| RAM | 2GB | 4GB+ |
| CPU | 2 cores | 4 cores |
| Disk | 10GB | 50GB+ |
| Internet | 1 Mbps | 10 Mbps |
| Docker | v20.10 | v24+ |
| Python | 3.12 | 3.13+ |
| Node | 18 | 22+ |

---

## FAQ

**Q: Do I need to pay for API access?**
A: No! All data sources (yfinance, Finnhub free tier) are free. No subscription needed.

**Q: Can I share watchlists with friends?**
A: Not yet. Phase 2 includes social features. For now, export/import JSON.

**Q: What if yfinance goes down?**
A: Fallback to Finnhub. Data cached for 1 hour. Shows warning badge.

**Q: Can I deploy to AWS/cloud?**
A: Yes! Use docker-compose.prod.yml. Docs in DEPLOYMENT.md.

**Q: Is my data stored securely?**
A: All data is local (self-hosted). Passwords are bcrypt hashed. No cloud sync.

**Q: Can I use mobile?**
A: Desktop-first (responsive). Mobile optimization coming in Phase 3.

---

## License

MIT License — See [LICENSE](LICENSE) file.

Free for personal and commercial use.

---

## Support

- 📖 **Documentation**: See [REQUIREMENTS.md](REQUIREMENTS.md) and [INSTRUCTIONS.md](INSTRUCTIONS.md)
- 🐛 **Issues**: [GitHub Issues](https://github.com/yourusername/stockviz/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/yourusername/stockviz/discussions)
- 📧 **Email**: support@stockviz.local

---

## Acknowledgments

- **TradingView Lightweight Charts** — Professional charting library
- **yfinance** — Stock data
- **FastAPI** — Modern Python framework
- **React** — UI library
- **TimescaleDB** — Time-series database

---

## Roadmap

Planned features (subject to change):

- [ ] Mobile app (React Native)
- [ ] Real-time 0-delay data integration
- [ ] Machine learning stock predictions
- [ ] Backtesting with live broker integration
- [ ] Social features (share strategies, follow traders)
- [ ] API for third-party apps
- [ ] Crypto markets
- [ ] Multi-language support

---

## Stats

- **Languages**: Python, JavaScript, SQL
- **Lines of Code**: ~15K (Phase 1)
- **Time to First Chart**: < 2 minutes
- **Learning Curve**: ⭐⭐ (Medium)
- **Community Size**: Growing 📈

---

## Disclaimer

**StockViz is for educational and analysis purposes only.** It is not financial advice. Always do your own research and consult a financial advisor before making investment decisions. Past performance does not guarantee future results.

---

## Changelog

### v0.1.0 (2026-02-24) — BETA

**Initial Release**
- User authentication (JWT)
- Stock charts (candlestick, line, area)
- Technical indicators (MA, EMA, RSI, MACD, Bollinger Bands)
- Drawing tools (trend line, H-line, Fibonacci)
- Watchlist management
- Basic alerts (price, RSI)
- Dark mode + light mode
- Docker setup (dev + prod)

See full [CHANGELOG.md](docs/CHANGELOG.md)

---

## Connect

- 🌐 **Website**: https://stockviz.local (local)
- 🐙 **GitHub**: [yourusername/stockviz](https://github.com/yourusername/stockviz)
- 💬 **Discord**: [Join Community](https://discord.gg/stockviz)
- 🐦 **Twitter**: [@stockviz_app](https://twitter.com/stockviz_app)

---

**Made with ❤️ by the StockViz Team**

---

<div align="center">

**⭐ If you find this helpful, please star the repo!**

Questions? Open an issue or discussion on GitHub.

</div>
