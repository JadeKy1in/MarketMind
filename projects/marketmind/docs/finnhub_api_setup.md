# Finnhub API Key Setup

Finnhub is MarketMind's secondary/fallback market data source, used when
yfinance is unavailable or times out. It provides US stock fundamentals
and historical price data through a free-tier REST API.

## 1. Get a Free API Key

1. Go to https://finnhub.io/register
2. Fill in your email and create a password
3. Verify your email (check inbox for confirmation link)
4. After verification, log in and your API key is displayed immediately
   on the dashboard at https://finnhub.io/dashboard

**Free tier limits:**
- 60 API calls per minute
- US stocks real-time data
- Forex and crypto data
- No credit card required

## 2. Add the Key to .env

Open `projects/marketmind/.env` (or create it from scratch) and add:

```
FINNHUB_KEY=your_key_here
```

Replace `your_key_here` with the actual key from your Finnhub dashboard.

Example:

```
FINNHUB_KEY=c123456789abcdef
```

**Important:** The `.env` file is listed in `.gitignore` and must never be
committed. It contains API keys that are secrets.

## 3. How MarketMind Uses Finnhub

**File:** `gateway/market_data.py`

Finnhub acts as a **secondary fallback** in the data fetching chain:

| Priority | Source | Requires Key |
|:--------:|--------|:------------:|
| 1 (primary) | yfinance | No |
| 2 (fallback) | **Finnhub** | Yes (`FINNHUB_KEY`) |
| 3 (crypto) | Binance public API | No |

MarketMind calls Finnhub only when yfinance fails or times out. Under normal
conditions, Finnhub is rarely hit, staying well within the 60 calls/min free quota.

### Endpoints Used

| Endpoint | Purpose | Data Type |
|----------|---------|:---------:|
| `/stock/profile2` | Company profile (name, industry, market cap, IPO date) | fundamentals |
| `/stock/metric` | Key financial metrics (P/E, P/B, EPS, ROE, etc.) | fundamentals |
| `/stock/candle` | Daily OHLCV candles (1 year lookback, resolution=D) | ohlcv / technical |

### Data Flow

```
get_market_data(ticker, data_type)
  |
  +-- _fetch_yfinance()        # primary, no API key
  |     if fails or empty --> _fetch_finnhub()   # fallback, uses FINNHUB_KEY
  |
  +-- if crypto ticker --> _fetch_binance()      # public REST, no key
```

### Sanitization

All string values returned by Finnhub pass through `defang_text()` before
reaching any caller, preventing prompt-injection vectors from reaching
L2/L3 LLM prompts.
