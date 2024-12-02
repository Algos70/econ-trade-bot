# Econ Trade Bot

A cryptocurrency trading bot project developed for Engineering Economics class. The bot implements various technical analysis strategies including SMA crossover, RSI, and Bollinger Bands to make trading decisions.

## Features

- Real-time trading with Binance API
- Multiple trading pair support (ETH, BTC, AVAX, SOL, RENDER, FET)
- Technical analysis indicators:
  - Simple Moving Average (SMA) crossover
  - Relative Strength Index (RSI)
  - Bollinger Bands
- Backtesting capabilities with different timeframes (15m, 1h, 4h, 1d)
- WebSocket integration for real-time price updates
- Stop-loss functionality
- Web API endpoints for control and monitoring

## Installation

1. Clone the repository:

```
git clone git@github.com:Algos70/econ-trade-bot.git
```

2. Install dependencies:

```
pip install -r requirements.txt
```

## Configuration

The bot uses Binance API for trading. You'll need to:

1. Create a Binance account
2. Generate API keys from your Binance account
3. Update the API keys in `services.py`

## Usage

1. Start the server:

```bash
python run.py
```

2. The API will be available at `http://127.0.0.1:5000`

### API Endpoints

- `POST /api/start-trade`: Start trading for all or specific pairs
- `POST /api/stop-trade`: Stop trading for all or specific pairs
- `GET /api/trading-status`: Get current trading status
- `POST /api/update-trade-parameters`: Update trading parameters
- `POST /api/backtest`: Run backtesting simulation

### Trading Parameters

You can customize the following parameters:
- `longterm_sma`: Long-term Simple Moving Average period (default: 20)
- `shortterm_sma`: Short-term Simple Moving Average period (default: 8)
- `rsi_period`: RSI calculation period (default: 8)
- `bb_length`: Bollinger Bands period (default: 20)
- `rsi_oversold`: RSI oversold threshold (default: 30)
- `rsi_overbought`: RSI overbought threshold (default: 70)

## Architecture

- Flask-based REST API
- WebSocket integration using Flask-SocketIO
- Real-time price data from Binance
- Pandas for technical analysis calculations
- Threading for concurrent trading operations

## Trading Strategy

The bot implements a combined strategy using:
1. SMA crossover for trend direction
2. RSI for overbought/oversold conditions
3. Bollinger Bands for price range analysis
4. Stop-loss protection (2% by default)

## Disclaimer

This bot is for educational purposes only. Cryptocurrency trading carries significant risks. Use at your own risk.