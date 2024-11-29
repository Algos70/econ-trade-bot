import asyncio
from binance import AsyncClient, BinanceSocketManager
import pandas_ta as ta
import pandas as pd

g_symbol = 'BTCUSDT'
g_cycle = 1
g_longterm = 40
g_shortterm = 24

class SmaCrossOver:
    def __init__(self, trade_state):
        self.trade_state = trade_state
        self._client = None
        self._price_info = None
        self._first_price_info_fut = None

    @classmethod
    async def create(cls, api_key, api_sec, testnet, trade_state):
        """Create and initialize the SmaCrossOver instance."""
        instance = cls(trade_state)
        instance._client = await AsyncClient.create(api_key, api_sec, tld="com", testnet=testnet)
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
        async with bm.kline_socket(symbol=g_symbol) as stream:
            self._price_info = await stream.recv()
            self._first_price_info_fut.set_result(True)
            while self.trade_state['running']:
                self._price_info = await stream.recv()
                #print(self._price_info)


    async def run(self):
        """Run the SMA crossover trading algorithm."""
        # Create an empty DataFrame to hold all kline data
        price_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])

        buy_price = 0
        state = 0

        await self._first_price_info_fut  # Wait until first price info is received.

        while self.trade_state['running']:
            # Extract the relevant kline data from the WebSocket message
            kline_data = self._price_info['k']  # 'k' contains the kline data
            
            # Create a dictionary with all kline data
            kline_dict = {
                "timestamp": kline_data['t'],
                "open": float(kline_data['o']),
                "high": float(kline_data['h']),
                "low": float(kline_data['l']),
                "close": float(kline_data['c']),
                "volume": float(kline_data['v']),
                "close_time": kline_data['T'],
                "quote_asset_volume": float(kline_data['q']),
                "number_of_trades": kline_data['n'],
                "taker_buy_base_asset_volume": float(kline_data['V']),
                "taker_buy_quote_asset_volume": float(kline_data['Q']),
                "ignore": kline_data['B']
            }

            # Convert kline_dict to a DataFrame for a single row
            kline_df = pd.DataFrame([kline_dict])

            # Concatenate the new row to the existing price_df
            price_df = pd.concat([price_df, kline_df], ignore_index=True)
            price_df = price_df.tail(g_longterm)

            # After accumulating enough data, perform SMA and RSI calculations
            if len(price_df) >= g_longterm:  # Perform analysis once enough data is available
                # Calculate long-term and short-term SMAs (use the closing prices)
                longterm_sma = price_df["close"].tail(g_longterm).mean()
                shortterm_sma = price_df["close"].tail(g_shortterm).mean()

                # Calculate RSI using pandas_ta
                rsi = await self.calculate_rsi_with_pandas_ta(price_df["close"], 14)
                if pd.isna(rsi):
                    rsi = 0
                print(f"RSI: {rsi} | Short-term SMA: {shortterm_sma} | Long-term SMA: {longterm_sma}")

                if state == 0 and shortterm_sma > longterm_sma and rsi < 30:
                    # Buy signal: SMA crossover and RSI indicates oversold condition
                    print(f"BUY: {kline_dict['close']} | Short SMA: {shortterm_sma} > Long SMA: {longterm_sma} | RSI: {rsi}")
                    buy_price = kline_dict['close']
                    state = 1  # Change state to "holding" position

                elif state == 1 and (shortterm_sma < longterm_sma or rsi > 70) and kline_dict['close'] - buy_price != 0:
                    # Sell signal: SMA crossover or RSI indicates overbought condition
                    print(f"SELL: {kline_dict['close']} | Profit: {kline_dict['close'] - buy_price} USDT | RSI: {rsi}")
                    state = 0  # Change state to "not holding" position

            await asyncio.sleep(g_cycle)
    async def calculate_rsi_with_pandas_ta(self, price_list, period=14):
        """Calculate the RSI using pandas_ta."""
        prices = pd.DataFrame(price_list, columns=["close"])
        prices = prices.iloc[::-1].reset_index(drop=True)

        prices["rsi"] = ta.rsi(prices["close"], length=period)
        return prices["rsi"].iloc[-1]

async def trade_with_timeout(trade_state):
    """Handles trading logic with SmaCrossOver and a 5-minute timeout."""
    api_key = "RLro7vCjhhhyet8dY7fBjAwvEWalSQBgrnhPCwBjX1vWiOQujgQ51KuEoyH2SnNM"
    api_sec = "Aq8BccImuXGNzlD3EFv9Lh4h0sQnSgWIZJrbCOvCXIZslcKeCM3hXVJ6sgjc0Fi0"
    testnet = True

    try:
        sma_crossover = await SmaCrossOver.create(api_key, api_sec, testnet, trade_state)
        await asyncio.gather(sma_crossover.fetch_price(), sma_crossover.run())
    except Exception as e:
        print(f"Error during trading: {e}")
    finally:
        trade_state['running'] = False
        await sma_crossover.close()
