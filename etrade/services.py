"""
This module contains the trading services for the econ-trade-bot API.
"""

import asyncio
from datetime import datetime, timedelta, timezone
# pylint: disable=import-error
from binance import AsyncClient, BinanceSocketManager, Client

# pylint: disable=import-error
import pandas_ta as ta
import pandas as pd
from .sockets import send_kline_data, send_buy_signal, send_sell_signal
from .config import Config


G_CYCLE = 1
G_LONGTERM = 50


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


class LiveTrade:
    """Class for live trading."""

    def __init__(self, trade_state, socketio):
        """Initialize the LiveTrade instance."""
        self.trade_state = trade_state
        self.socketio = socketio
        self.price_manager = None
        self.technical_analyzer = TechnicalAnalyzer()
        self.trade_executor = TradeExecutor()
        self.signal_generator = SignalGenerator()

    @classmethod
    async def create(cls, api_key, api_sec, trade_state, socketio, symbol):
        """Create and initialize the LiveTrade instance."""
        instance = cls(trade_state, socketio)
        client = await AsyncClient.create(api_key, api_sec, tld="com")
        instance.price_manager = PriceDataManager(client, symbol)
        return instance

    async def close(self):
        """Close the Binance client connection."""
        if self.price_manager.client:
            await self.price_manager.client.close_connection()

    async def run(self, trade_parameters):
        """Run the SMA crossover trading algorithm."""
        price_df = pd.DataFrame(
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base_asset_volume",
                "taker_buy_quote_asset_volume",
                "ignore",
            ]
        )
        historical_klines = await self.price_manager.client.get_klines(
            symbol=self.price_manager.symbol,
            interval=Client.KLINE_INTERVAL_1MINUTE,
            limit=G_LONGTERM,
        )
        price_df = await self.price_manager.process_historical_klines(
            historical_klines, price_df, self.socketio
        )
        buy_price = 0
        state = 0

        await self.price_manager.first_price_info_fut
        while self.trade_state["running"]:
            kline_data = self.price_manager.price_info["k"]
            send_kline_data(self.socketio, self.price_manager.price_info)

            kline_dict = {
                "timestamp": kline_data["t"],
                "open": float(kline_data["o"]),
                "high": float(kline_data["h"]),
                "low": float(kline_data["l"]),
                "close": float(kline_data["c"]),
                "volume": float(kline_data["v"]),
                "close_time": kline_data["T"],
                "quote_asset_volume": float(kline_data["q"]),
                "number_of_trades": kline_data["n"],
                "taker_buy_base_asset_volume": float(kline_data["V"]),
                "taker_buy_quote_asset_volume": float(kline_data["Q"]),
                "ignore": kline_data["B"],
            }

            kline_df = pd.DataFrame([kline_dict])
            price_df = pd.concat([price_df, kline_df], ignore_index=True)
            price_df = price_df.tail(G_LONGTERM)

            longterm_sma, shortterm_sma = await self.technical_analyzer.calculate_sma(
                price_df,
                trade_parameters["longterm_sma"],
                trade_parameters["shortterm_sma"],
            )
            rsi = await self.technical_analyzer.calculate_rsi_with_pandas_ta(
                price_df["close"], trade_parameters["rsi_period"]
            )
            bb_upper, bb_lower = (
                await self.technical_analyzer.calculate_bollinger_bands(
                    price_df, trade_parameters["bb_lenght"]
                )
            )

            current_price = float(kline_dict["close"])
            if self.signal_generator.check_buy_signal(
                state,
                shortterm_sma,
                longterm_sma,
                rsi,
                bb_lower,
                current_price,
                trade_parameters["rsi_oversold"],
            ):
                await self.trade_executor.execute_buy(
                    kline_dict, current_price, self.price_manager.symbol, self.socketio
                )
                buy_price = current_price
                state = 1
            elif self.signal_generator.check_sell_signal(
                state,
                shortterm_sma,
                longterm_sma,
                rsi,
                bb_upper,
                current_price,
                buy_price,
                trade_parameters["rsi_overbought"],
            ):
                await self.trade_executor.execute_sell(
                    kline_dict,
                    current_price,
                    buy_price,
                    self.price_manager.symbol,
                    self.socketio,
                )
                buy_price = 0
                state = 0
            await asyncio.sleep(G_CYCLE)


class Backtest:
    """Class for backtesting."""

    def __init__(self, symbol):
        """Initialize the Backtest instance."""
        self._client = None
        self.now = datetime.now(timezone.utc)
        self.historical_days = 120
        self.past = str(self.now - timedelta(days=self.historical_days))
        self.symbol = symbol
        self.bar_length1 = "15m"
        self.bar_length2 = "1h"
        self.bar_length3 = "4h"
        self.bar_length4 = "1d"
        self.initial_amount = 10000
        self.money1 = self.initial_amount
        self.money2 = self.initial_amount
        self.money3 = self.initial_amount
        self.money4 = self.initial_amount
        self.etc_amount1 = 0
        self.etc_amount2 = 0
        self.etc_amount3 = 0
        self.etc_amount4 = 0
        self.stop_loss_percentage = 0.02

    @classmethod
    async def create(cls, symbol, api_key, api_sec):
        """Create and initialize the Backtest instance."""
        instance = cls(symbol)
        instance._client = await AsyncClient.create(api_key, api_sec, tld="com")
        return instance

    def generate_buy_signals(self, df, rsi):
        """Generate buy signals based on the given conditions."""
        df["buy_signal"] = (
            (df["Close"] <= df["bb_lower"])
            & (df["rsi"] < rsi)
            & (df["shortterm_sma"] > df["longterm_sma"])
        )
        return df

    def generate_sell_signal(self, df, rsi):
        """Generate sell signals based on the given conditions."""
        df["sell_signal"] = (
            (df["Close"] >= df["bb_upper"])
            & (df["rsi"] > rsi)
            & (df["shortterm_sma"] < df["longterm_sma"])
        )
        return df

    def execute_trades_with_stop_loss(
        self, df, money, etc_amount, stop_loss_percentage, symbol
    ):
        """Execute trades with stop-loss."""
        stop_loss_price = None
        trade_signals = []  # Array to store all trading signals

        for index, row in df.iterrows(): # pylint: disable=unused-variable
            if row["buy_signal"] and money > 0:
                etc_to_buy = money / row["Close"]
                etc_amount += etc_to_buy
                stop_loss_price = row["Close"] * (1 - stop_loss_percentage)
                money = 0
                # Store buy signal
                trade_signals.append(
                    {
                        "date": row.name,
                        "type": "BUY",
                        "price": row["Close"],
                        "amount": etc_to_buy,
                        "total": etc_to_buy * row["Close"],
                    }
                )
                continue

            if (
                stop_loss_price is not None
                and row["Close"] <= stop_loss_price
                and etc_amount > 0
            ):
                sell_value = etc_amount * row["Close"]
                money += sell_value
                # Store stop-loss signal
                trade_signals.append(
                    {
                        "date": row.name,
                        "type": "STOP_LOSS",
                        "price": row["Close"],
                        "amount": etc_amount,
                        "total": sell_value,
                    }
                )
                etc_amount = 0
                stop_loss_price = None

            elif row["sell_signal"] and etc_amount > 0:
                sell_value = etc_amount * row["Close"]
                money += sell_value
                # Store sell signal
                trade_signals.append(
                    {
                        "date": row.name,
                        "type": "SELL",
                        "price": row["Close"],
                        "amount": etc_amount,
                        "total": sell_value,
                    }
                )
                etc_amount = 0
                stop_loss_price = None

        # Handle final sell if needed
        if etc_amount > 0:
            final_price = df.iloc[-1]["Close"]
            final_value = etc_amount * final_price
            money += final_value
            # Store final sell signal
            trade_signals.append(
                {
                    "date": df.index[-1],
                    "type": "FINAL_SELL",
                    "price": final_price,
                    "amount": etc_amount,
                    "total": final_value,
                }
            )
            print(
                f"Final sell at end: Price = {final_price}, {symbol} sold = {etc_amount}"
            )
            etc_amount = 0

        return money, trade_signals

    async def run(self, parameters):
        """Run the backtest."""
        bars1 = await self._client.get_historical_klines(
            symbol=self.symbol,
            interval=self.bar_length1,
            start_str=self.past,
            end_str=str(self.now),
        )
        bars2 = await self._client.get_historical_klines(
            symbol=self.symbol,
            interval=self.bar_length2,
            start_str=self.past,
            end_str=str(self.now),
        )
        bars3 = await self._client.get_historical_klines(
            symbol=self.symbol,
            interval=self.bar_length3,
            start_str=self.past,
            end_str=str(self.now),
        )
        bars4 = await self._client.get_historical_klines(
            symbol=self.symbol,
            interval=self.bar_length4,
            start_str=self.past,
            end_str=str(self.now),
        )
        df1 = await self.construct_dataframe(bars1)
        df2 = await self.construct_dataframe(bars2)
        df3 = await self.construct_dataframe(bars3)
        df4 = await self.construct_dataframe(bars4)

        dfs = {"df1": df1, "df2": df2, "df3": df3, "df4": df4}
        for df in dfs.values():
            bb = ta.bbands(df["Close"], length=parameters["bb_lenght"])
            df[["bb_lower", "bb_middle", "bb_upper"]] = bb.iloc[:, :3]
            df["rsi"] = ta.rsi(df["Close"], length=parameters["rsi_period"])
            df["shortterm_sma"] = ta.sma(
                df["Close"], length=parameters["shortterm_sma"]
            )
            df["longterm_sma"] = ta.sma(df["Close"], length=parameters["longterm_sma"])

            df = self.generate_buy_signals(df, parameters["rsi_oversold"])
            df = self.generate_sell_signal(df, parameters["rsi_overbought"])
            df.dropna(inplace=True)

        self.money1, signals1 = self.execute_trades_with_stop_loss(
            df1, self.money1, self.etc_amount1, self.stop_loss_percentage, self.symbol
        )
        self.money2, signals2 = self.execute_trades_with_stop_loss(
            df2, self.money2, self.etc_amount2, self.stop_loss_percentage, self.symbol
        )
        self.money3, signals3 = self.execute_trades_with_stop_loss(
            df3, self.money3, self.etc_amount3, self.stop_loss_percentage, self.symbol
        )
        self.money4, signals4 = self.execute_trades_with_stop_loss(
            df4, self.money4, self.etc_amount4, self.stop_loss_percentage, self.symbol
        )

        return {
            self.bar_length1: {
                "df": df1.reset_index().to_dict("records"),
                "signals": signals1,
                "initial_amount": self.initial_amount,
                "money": self.money1,
                "profit": (self.money1 - self.initial_amount),
            },
            self.bar_length2: {
                "df": df2.reset_index().to_dict("records"),
                "signals": signals2,
                "initial_amount": self.initial_amount,
                "money": self.money2,
                "profit": (self.money2 - self.initial_amount),
            },
            self.bar_length3: {
                "df": df3.reset_index().to_dict("records"),
                "signals": signals3,
                "initial_amount": self.initial_amount,
                "money": self.money3,
                "profit": (self.money3 - self.initial_amount),
            },
            self.bar_length4: {
                "df": df4.reset_index().to_dict("records"),
                "signals": signals4,
                "initial_amount": self.initial_amount,
                "money": self.money4,
                "profit": (self.money4 - self.initial_amount),
            },
        }

    async def construct_dataframe(self, bars):
        """Construct a dataframe from the given bars."""
        df = pd.DataFrame(bars)
        df["Date"] = pd.to_datetime(df.iloc[:, 0], unit="ms")
        df.columns = [
            "Open Time",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Clos Time",
            "Quote Asset Volume",
            "Number of Trades",
            "Taker Buy Base Asset Volume",
            "Taker Buy Quote Asset Volume",
            "Ignore",
            "Date",
        ]
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
        df.set_index("Date", inplace=True)
        for column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        return df


async def trade_with_timeout(trade_state, trade_parameters, socketio):
    """Handles trading logic with LiveTrade."""
    api_key = Config.API_KEY
    api_sec = Config.API_SECRET

    try:
        symbol = trade_parameters["symbol"]
        live_trade = await LiveTrade.create(
            api_key, api_sec, trade_state, socketio, symbol
        )
        await asyncio.gather(
            live_trade.price_manager.fetch_price(trade_state), live_trade.run(trade_parameters)
        )
    except Exception as e:
        print(f"Error during trading {trade_parameters['symbol']}: {e}")
    finally:
        trade_state["running"] = False
        await live_trade.close()


async def start_backtest(symbol, parameters):
    """Start the backtest."""
    try:
        api_key = Config.API_KEY
        api_sec = Config.API_SECRET
        backtest = await Backtest.create(symbol, api_key, api_sec)
        result = await backtest.run(parameters)
        return result
    except Exception as e:
        print(f"Error during backtest: {e}")
        return None
