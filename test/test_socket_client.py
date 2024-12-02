import socketio
import time
from datetime import datetime

# Create a Socket.IO client
sio = socketio.Client()


# Event handlers
@sio.event
def connect():
    print("Connected to server")


@sio.event
def disconnect():
    print("Disconnected from server")


"""
@sio.on('kline_data')
def on_kline_data(data):
    kline = data['k']
    print(f'Kline: Symbol: {kline["s"]}, Close: {kline["c"]}, High: {kline["h"]}, Low: {kline["l"]}')
"""


@sio.on("buy_signal")
def on_buy_signal(data):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{timestamp}")
    print(f'🟢 BUY SIGNAL for {data["symbol"]}:')
    print(f'    Price: ${data["close"]}')
    print(f'    Trade Amount: ${data["trade_amount"]}')
    print(f'    Current Balance: ${data["balance"]}')
    print(f'    Holdings Value: ${data["holdings_value"]}')
    print(f'    Total Value: ${data["total_value"]}')
    print(f'    Total Profit: ${data["total_profit"]}')
    print(f'    Trades Made: {data["trades_made"]}')


@sio.on("sell_signal")
def on_sell_signal(data):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{timestamp}")
    print(f'🔴 SELL SIGNAL for {data["symbol"]}:')
    print(f'    Price: ${data["close"]}')
    print(f'    Trade Profit: ${data["trade_profit"]}')
    print(f'    Current Balance: ${data["balance"]}')
    print(f'    Total Value: ${data["total_value"]}')
    print(f'    Total Profit: ${data["total_profit"]}')
    print(f'    Trades Made: {data["trades_made"]}')


if __name__ == "__main__":
    try:
        sio.connect("http://127.0.0.1:5000")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDisconnecting from server...")
        sio.disconnect()
    except Exception as e:
        print(f"Error: {e}")
