import asyncio
from binance import AsyncClient, BinanceSocketManager
import pandas_ta as ta
import pandas as pd

g_symbol = 'BTCUSDT'
g_cycle = 1
g_longterm = 80
g_shortterm = 45

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
        async with bm.symbol_book_ticker_socket(symbol=g_symbol) as stream:
            self._price_info = await stream.recv()
            self._first_price_info_fut.set_result(True)
            while self.trade_state['running']:
                self._price_info = await stream.recv()

    async def run(self):
        """Run the SMA crossover trading algorithm."""
        price_list = [0] * g_longterm
        buy_price = 0
        cnt = 1
        state = 0

        await self._first_price_info_fut

        while self.trade_state['running']:
            curr_price = float(self._price_info['b'])
            price_list[1:] = price_list[:-1]
            price_list[0] = curr_price
            print(self._price_info)
            if cnt >= g_longterm:
                longterm_sma = sum(price_list) / g_longterm
                shortterm_sma = sum(price_list[:g_shortterm]) / g_shortterm

                rsi = await self.calculate_rsi_with_pandas_ta(price_list, 14)
                if state == 0 and shortterm_sma > longterm_sma and rsi < 30:
                    # Buy signal: SMA crossover and RSI indicates oversold condition
                    print(f"BUY: {curr_price} | Short SMA: {shortterm_sma} > Long SMA: {longterm_sma} | RSI: {rsi}")
                    buy_price = curr_price
                    state = 1
                elif state == 1 and (shortterm_sma < longterm_sma or rsi > 70):
                    # Sell signal: SMA crossover or RSI indicates overbought condition
                    print(f"SELL: {curr_price} | Profit: {curr_price - buy_price} USDT | RSI: {rsi}")
                    state = 0
            cnt+=1
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
