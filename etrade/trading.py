"""
This module contains trading-related helper classes for the econ-trade-bot.
"""
import asyncio
from datetime import datetime, timezone

import pandas as pd # pylint: disable=import-error
import pandas_ta as ta # pylint: disable=import-error
from binance import BinanceSocketManager# pylint: disable=import-error
from .sockets import send_kline_data, send_buy_signal, send_sell_signal
# pylint: disable=import-error


class PriceDataManager:
    """Class for fetching and processing price data."""

    def __init__(self, client, symbol):
        """Initialize the PriceDataManager instance."""
        self._client = client
        self.symbol = symbol
        self._price_info = None
        self._first_price_info_fut = asyncio.Future()

    @property
    def client(self):
        """Get the client."""
        return self._client

    @property
    def first_price_info_fut(self):
        """Get the first price info future."""
        return self._first_price_info_fut

    @property
    def price_info(self):
        """Get the price info."""
        return self._price_info

    async def fetch_price(self, trade_state):
        """Fetch price data asynchronously from Binance."""
        bm = BinanceSocketManager(self._client)
        async with bm.kline_socket(symbol=self.symbol) as stream:
            self._price_info = await stream.recv()
            self._first_price_info_fut.set_result(True)
            while trade_state["running"]:
                self._price_info = await stream.recv()

    async def process_historical_klines(self, historical_klines, price_df, socketio):
        """Process historical klines."""
        kline_data_list = []  # Collect kline dictionaries for batch processing

        for i, kline in enumerate(historical_klines):
            kline_dict = {
                "timestamp": kline[0],
                "open": float(kline[1]),
                "high": float(kline[2]),
                "low": float(kline[3]),
                "close": float(kline[4]),
                "volume": float(kline[5]),
                "close_time": kline[6],
                "quote_asset_volume": float(kline[7]),
                "number_of_trades": kline[8],
                "taker_buy_base_asset_volume": float(kline[9]),
                "taker_buy_quote_asset_volume": float(kline[10]),
                "ignore": kline[11],
            }
            kline_data_list.append(kline_dict)

            # Create kline data for websocket
            current_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            historical_event_time = current_time - (
                (50 - i) * 1000
            )  # Start from 50 seconds ago
            historical_kline_data = {
                "e": "kline",
                "E": historical_event_time,
                "s": self.symbol,
                "k": {
                    "t": kline[0],
                    "T": kline[6],
                    "s": self.symbol,
                    "i": "1m",
                    "f": kline[8],
                    "L": kline[8],
                    "o": str(kline[1]),
                    "c": str(kline[4]),
                    "h": str(kline[2]),
                    "l": str(kline[3]),
                    "v": str(kline[5]),
                    "n": kline[8],
                    "x": True,
                    "q": str(kline[7]),
                    "V": str(kline[9]),
                    "Q": str(kline[10]),
                    "B": str(kline[11]),
                },
            }
            send_kline_data(socketio, historical_kline_data)

        # Combine all kline data into a DataFrame
        if kline_data_list:
            kline_df = pd.DataFrame(kline_data_list)
            if not kline_df.isna().all(axis=None):
                price_df = pd.concat([price_df, kline_df], ignore_index=True)

        return price_df


class TechnicalAnalyzer:
    """Class for calculating technical indicators."""

    def __init__(self):
        pass

    async def calculate_sma(self, price_df, longterm_sma, shortterm_sma):
        """Calculate the SMA"""
        try:
            price_df["longterm_sma"] = ta.sma(price_df["close"], length=longterm_sma)
            price_df["shortterm_sma"] = ta.sma(price_df["close"], length=shortterm_sma)
            return price_df["longterm_sma"].iloc[-1], price_df["shortterm_sma"].iloc[-1]
        except Exception as e:
            print(f"Error calculating SMA: {e}")
            return 0, 0

    async def calculate_bollinger_bands(self, price_df, period):
        """Calculate all technical indicators"""
        try:
            bb = ta.bbands(price_df["close"], length=period)
            bb.columns = ["lower_b", "middle_b", "upper_b", "b_p", "p_p"]
            return bb["upper_b"].iloc[-1], bb["lower_b"].iloc[-1]
        except Exception as e:
            print(f"Error calculating Bollinger Bands: {e}")
            return 0, 0

    async def calculate_rsi_with_pandas_ta(self, price_list, period=14):
        """Calculate the RSI using pandas_ta."""
        try:
            prices = pd.DataFrame(price_list, columns=["close"])
            prices["rsi"] = ta.rsi(prices["close"], length=period)
            if pd.isna(prices["rsi"].iloc[-1]):
                return 0
            return prices["rsi"].iloc[-1]
        except Exception as e:
            print(f"Error calculating RSI: {e}")
            return 0


class SignalGenerator:
    """Class for generating trading signals."""

    def __init__(self, stop_loss_pct=0.02):
        self.stop_loss_pct = stop_loss_pct

    def check_buy_signal(
        self,
        state,
        shortterm_sma,
        longterm_sma,
        rsi,
        bb_lower,
        current_price,
        rsi_oversold,
    ):
        """Check if buy conditions are met"""
        try:
            return (
                state == 0
                and float(shortterm_sma) > float(longterm_sma)
                and float(rsi) < float(rsi_oversold)
                and float(current_price) < float(bb_lower)
            )
        except Exception as e:
            print(f"Error checking buy signal: {e}")
            return False

    def check_sell_signal(
        self,
        state,
        shortterm_sma,
        longterm_sma,
        rsi,
        bb_upper,
        current_price,
        buy_price,
        rsi_overbought,
    ):
        """Check if sell conditions are met"""
        try:
            return (
                state == 1
                and (
                    float(shortterm_sma) < float(longterm_sma)
                    and float(rsi) > float(rsi_overbought)
                    and float(current_price) > float(bb_upper)
                    or float(current_price) - float(buy_price)
                    > self.stop_loss_pct * float(buy_price)
                )
                and float(current_price) - float(buy_price) != 0
            )
        except Exception as e:
            print(f"Error checking sell signal: {e}")
            return False

class TradeExecutor:
    """Class for executing trades."""

    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.holdings = 0
        self.total_profit = 0
        self.trades_made = 0

    async def execute_buy(self, kline_dict, current_price, symbol, socketio):
        """Handle buy logic"""
        try:
            # Calculate trade amount (40% of current balance)
            trade_amount = self.balance * 0.4

            if trade_amount >= 10:  # Minimum trade size
                self.holdings = trade_amount / current_price
                self.balance -= trade_amount
                self.trades_made += 1
                trade_info = {
                    **kline_dict,
                    "symbol": symbol,
                    "close": current_price,
                    "balance": round(self.balance, 2),
                    "holdings_value": round(self.holdings * current_price, 2),
                    "total_value": round(
                        self.balance + (self.holdings * current_price), 2
                    ),
                    "trade_amount": round(trade_amount, 2),
                    "total_profit": round(self.total_profit, 2),
                    "trades_made": self.trades_made,
                }
                send_buy_signal(socketio, trade_info)
                return trade_amount
        except Exception as e:
            print(f"Error executing buy: {e}")
            return 0

    async def execute_sell(
        self, kline_dict, current_price, buy_price, symbol, socketio
    ):
        """Handle sell logic and calculate profit return trade_profit"""
        try:
            sell_value = self.holdings * current_price
            trade_profit = sell_value - (self.holdings * buy_price)
            self.balance += sell_value
            self.total_profit += trade_profit
            self.holdings = 0

            trade_info = {
                **kline_dict,
                "symbol": symbol,
                "close": current_price,
                "balance": round(self.balance, 2),
                "trade_profit": round(trade_profit, 2),
                "total_value": round(self.balance, 2),
                "total_profit": round(self.total_profit, 2),
                "trades_made": self.trades_made,
            }
            send_sell_signal(socketio, trade_info)
            return trade_profit
        except Exception as e:
            print(f"Error executing sell: {e}")
            return 0
