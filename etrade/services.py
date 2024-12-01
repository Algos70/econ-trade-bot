import asyncio
from binance import AsyncClient, BinanceSocketManager
import pandas_ta as ta
import pandas as pd
from .sockets import send_kline_data, send_buy_signal, send_sell_signal

g_cycle = 1
g_longterm = 50
g_shortterm = 24

class SmaCrossOver:
    def __init__(self, trade_state, socketio, symbol):
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
        """Create and initialize the SmaCrossOver instance."""
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
            while self.trade_state['running']:
                self._price_info = await stream.recv()

    async def run(self, trade_parameters):
        """Run the SMA crossover trading algorithm."""
        price_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", 
                                       "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", 
                                       "taker_buy_quote_asset_volume", "ignore"])

        buy_price = 0
        stop_loss_price = 0
        state = 0
        
        await self._first_price_info_fut

        while self.trade_state['running']:
            kline_data = self._price_info['k']
            send_kline_data(self.socketio, self._price_info)

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

            kline_df = pd.DataFrame([kline_dict])
            price_df = pd.concat([price_df, kline_df], ignore_index=True)
            price_df = price_df.tail(g_longterm)

            if len(price_df) >= g_longterm:
                price_df["longterm_sma"] = ta.sma(price_df["close"], length=trade_parameters['longterm_sma'])
                price_df["shortterm_sma"] = ta.sma(price_df["close"], length=trade_parameters['shortterm_sma'])

                longterm_sma = price_df["longterm_sma"].iloc[-1]
                shortterm_sma = price_df["shortterm_sma"].iloc[-1]

                rsi = await self.calculate_rsi_with_pandas_ta(price_df["close"], trade_parameters['rsi_period'])
                if pd.isna(rsi):
                    rsi = 0

                bb = ta.bbands(price_df["close"], length=trade_parameters['bb_lenght'])
                bb.columns = ["lower_b", "middle_b", "upper_b", "b_p", "p_p"]

                bb_lower = bb["lower_b"].iloc[-1]
                bb_upper = bb["upper_b"].iloc[-1]
                print("parameters", trade_parameters)
                if state == 0 and shortterm_sma > longterm_sma and rsi < trade_parameters['rsi_oversold'] and price_df["close"].iloc[-1] < bb_lower:
                    # Calculate trade amount (40% of current balance)
                    trade_amount = self.balance * 0.4
                    current_price = float(kline_dict['close'])
                    
                    if trade_amount >= 10:  # Minimum trade size
                        self.holdings = trade_amount / current_price
                        self.balance -= trade_amount
                        buy_price = current_price
                        state = 1
                        self.trades_made += 1
                        
                        trade_info = {
                            **kline_dict,
                            'symbol': self.symbol,
                            'close': current_price,
                            'balance': round(self.balance, 2),
                            'holdings_value': round(self.holdings * current_price, 2),
                            'total_value': round(self.balance + (self.holdings * current_price), 2),
                            'trade_amount': round(trade_amount, 2),
                            'total_profit': round(self.total_profit, 2),
                            'trades_made': self.trades_made
                        }
                        
                        print(f"{self.symbol} BUY: ${current_price:.2f} | Amount: ${trade_amount:.2f} | Balance: ${self.balance:.2f}")
                        send_buy_signal(self.socketio, trade_info)

                elif (state == 1 and (shortterm_sma < longterm_sma or rsi > trade_parameters['rsi_overbought'] or price_df["close"].iloc[-1] > bb_upper
                                      or price_df["close"].iloc[-1] - buy_price > self.stop_loss_pct * buy_price)) and current_price - buy_price != 0:
                    current_price = float(kline_dict['close'])
                    sell_value = self.holdings * current_price
                    trade_profit = sell_value - (self.holdings * buy_price)
                    
                    self.balance += sell_value
                    self.total_profit += trade_profit
                    
                    trade_info = {
                        **kline_dict,
                        'symbol': self.symbol,
                        'close': current_price,
                        'balance': round(self.balance, 2),
                        'trade_profit': round(trade_profit, 2),
                        'total_value': round(self.balance, 2),
                        'total_profit': round(self.total_profit, 2),
                        'trades_made': self.trades_made
                    }
                    
                    print(f"{self.symbol} SELL: ${current_price:.2f} | Profit: ${trade_profit:.2f} | Balance: ${self.balance:.2f}")
                    send_sell_signal(self.socketio, trade_info)
                    
                    state = 0
                    self.holdings = 0
                    buy_price = 0

            await asyncio.sleep(g_cycle)

    async def calculate_rsi_with_pandas_ta(self, price_list, period=14):
        """Calculate the RSI using pandas_ta."""
        prices = pd.DataFrame(price_list, columns=["close"])
        prices["rsi"] = ta.rsi(prices["close"], length=period)
        return prices["rsi"].iloc[-1]

async def trade_with_timeout(trade_state, trade_parameters, socketio):
    """Handles trading logic with SmaCrossOver."""
    api_key = "RLro7vCjhhhyet8dY7fBjAwvEWalSQBgrnhPCwBjX1vWiOQujgQ51KuEoyH2SnNM"
    api_sec = "Aq8BccImuXGNzlD3EFv9Lh4h0sQnSgWIZJrbCOvCXIZslcKeCM3hXVJ6sgjc0Fi0"

    try:
        symbol = trade_parameters['symbol']
        sma_crossover = await SmaCrossOver.create(api_key, api_sec, trade_state, socketio, symbol)
        await asyncio.gather(sma_crossover.fetch_price(), sma_crossover.run(trade_parameters))
    except Exception as e:
        print(f"Error during trading {trade_parameters['symbol']}: {e}")
    finally:
        trade_state['running'] = False
        await sma_crossover.close()
