import socketio
import time

# Create a Socket.IO client
sio = socketio.Client()

# Event handlers
@sio.event
def connect():
    print('Connected to server')

@sio.event
def disconnect():
    print('Disconnected from server')

@sio.on('kline_data')
def on_kline_data(data):
    print(f'Received kline data: {data}')

@sio.on('buy_signal')
def on_buy_signal(data):
    print(f'🟢 BUY SIGNAL: Price: {data["c"]}')

@sio.on('sell_signal')
def on_sell_signal(data):
    print(f'🔴 SELL SIGNAL: Price: {data["c"]}')

if __name__ == '__main__':
    try:
        # Connect to the server
        sio.connect('http://127.0.0.1:5000')
        
        # Keep the script running
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nDisconnecting from server...")
        sio.disconnect()
    except Exception as e:
        print(f"Error: {e}") 