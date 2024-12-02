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


G_CYCLE = 1
G_LONGTERM = 50


class LiveTrade:
    """Class for live trading."""

    def __init__(self, trade_state, socketio, symbol):
        """Initialize the LiveTrade instance."""
        self.trade_state = trade_state
        self._client = None
        self._price_info = None
        self._first_price_info_fut = None
        self.socketio = socketio
        self.symbol = symbol
        self.balance = 10000.0
        self.holdings = 0
        self.total_profit = 0
        self.trades_made = 0
        self.stop_loss_pct = 0.02

    @classmethod
    async def create(cls, api_key, api_sec, trade_state, socketio, symbol):
        """Create and initialize the LiveTrade instance."""
        instance = cls(trade_state, socketio, symbol)
        instance._client = await AsyncClient.create(api_key, api_sec, tld="com")
        loop = asyncio.get_running_loop()
        instance._first_price_info_fut = loop.create_future()
        return instance

    async def close(self):
        """Close the Binance client connection."""
        if self._client:
            await self._client.close_connection()

    async def fetch_price(self):
        """Fetch price data asynchronously from Binance."""
        bm = BinanceSocketManager(self._client)
        async with bm.kline_socket(symbol=self.symbol) as stream:
            self._price_info = await stream.recv()
            self._first_price_info_fut.set_result(True)
            while self.trade_state["running"]:
                self._price_info = await stream.recv()

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
        historical_klines = await self._client.get_klines(
            symbol=self.symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=G_LONGTERM
        )
        price_df = await self.process_historical_klines(historical_klines, price_df)
        buy_price = 0
        state = 0

        await self._first_price_info_fut
        while self.trade_state["running"]:
            kline_data = self._price_info["k"]
            send_kline_data(self.socketio, self._price_info)

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
            if len(price_df) >= G_LONGTERM:
                price_df["longterm_sma"] = ta.sma(
                    price_df["close"], length=trade_parameters["longterm_sma"]
                )
                price_df["shortterm_sma"] = ta.sma(
                    price_df["close"], length=trade_parameters["shortterm_sma"]
                )

                longterm_sma = price_df["longterm_sma"].iloc[-1]
                shortterm_sma = price_df["shortterm_sma"].iloc[-1]

                rsi = await self.calculate_rsi_with_pandas_ta(
                    price_df["close"], trade_parameters["rsi_period"]
                )
                if pd.isna(rsi):
                    rsi = 0

                bb = ta.bbands(price_df["close"], length=trade_parameters["bb_lenght"])
                bb.columns = ["lower_b", "middle_b", "upper_b", "b_p", "p_p"]

                bb_lower = bb["lower_b"].iloc[-1]
                bb_upper = bb["upper_b"].iloc[-1]
                current_price = float(kline_dict["close"])
                if (
                    state == 0
                    and float(shortterm_sma) > float(longterm_sma)
                    and float(rsi) < float(trade_parameters["rsi_oversold"])
                    and float(price_df["close"].iloc[-1]) < float(bb_lower)
                ):
                    # Calculate trade amount (40% of current balance)
                    trade_amount = self.balance * 0.4

                    if trade_amount >= 10:  # Minimum trade size
                        self.holdings = trade_amount / current_price
                        self.balance -= trade_amount
                        buy_price = current_price
                        state = 1
                        self.trades_made += 1

                        trade_info = {
                            **kline_dict,
                            "symbol": self.symbol,
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

                        send_buy_signal(self.socketio, trade_info)

                elif (
                    state == 1
                    and (
                        float(shortterm_sma) < float(longterm_sma)
                        and float(rsi) > float(trade_parameters["rsi_overbought"])
                        and float(price_df["close"].iloc[-1]) > float(bb_upper)
                        or float(price_df["close"].iloc[-1]) - float(buy_price)
                        > self.stop_loss_pct * float(buy_price)
                    )
                    and float(current_price) - float(buy_price) != 0
                ):
                    sell_value = self.holdings * current_price
                    trade_profit = sell_value - (self.holdings * buy_price)

                    self.balance += sell_value
                    self.total_profit += trade_profit

                    trade_info = {
                        **kline_dict,
                        "symbol": self.symbol,
                        "close": current_price,
                        "balance": round(self.balance, 2),
                        "trade_profit": round(trade_profit, 2),
                        "total_value": round(self.balance, 2),
                        "total_profit": round(self.total_profit, 2),
                        "trades_made": self.trades_made,
                    }

                    send_sell_signal(self.socketio, trade_info)

                    state = 0
                    self.holdings = 0
                    buy_price = 0

            await asyncio.sleep(G_CYCLE)

    async def calculate_rsi_with_pandas_ta(self, price_list, period=14):
        """Calculate the RSI using pandas_ta."""
        prices = pd.DataFrame(price_list, columns=["close"])
        prices["rsi"] = ta.rsi(prices["close"], length=period)
        return prices["rsi"].iloc[-1]

    async def process_historical_klines(self, historical_klines, price_df):
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
            historical_event_time = current_time - ((50 - i) * 1000)  # Start from 50 seconds ago
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
            send_kline_data(self.socketio, historical_kline_data)

        # Combine all kline data into a DataFrame
        if kline_data_list:
            kline_df = pd.DataFrame(kline_data_list)
            if not kline_df.isna().all(axis=None):
                price_df = pd.concat([price_df, kline_df], ignore_index=True)

        return price_df


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

        for index, row in df.iterrows():
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
    api_key = "RLro7vCjhhhyet8dY7fBjAwvEWalSQBgrnhPCwBjX1vWiOQujgQ51KuEoyH2SnNM"
    api_sec = "Aq8BccImuXGNzlD3EFv9Lh4h0sQnSgWIZJrbCOvCXIZslcKeCM3hXVJ6sgjc0Fi0"

    try:
        symbol = trade_parameters["symbol"]
        sma_crossover = await LiveTrade.create(
            api_key, api_sec, trade_state, socketio, symbol
        )
        await asyncio.gather(
            sma_crossover.fetch_price(), sma_crossover.run(trade_parameters)
        )
    except Exception as e:
        print(f"Error during trading {trade_parameters['symbol']}: {e}")
    finally:
        trade_state["running"] = False
        await sma_crossover.close()


async def start_backtest(symbol, parameters):
    """Start the backtest."""
    api_key = "RLro7vCjhhhyet8dY7fBjAwvEWalSQBgrnhPCwBjX1vWiOQujgQ51KuEoyH2SnNM"
    api_sec = "Aq8BccImuXGNzlD3EFv9Lh4h0sQnSgWIZJrbCOvCXIZslcKeCM3hXVJ6sgjc0Fi0"
    backtest = await Backtest.create(symbol, api_key, api_sec)
    result = await backtest.run(parameters)
    return result
