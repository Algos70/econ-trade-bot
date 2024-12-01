from flask_socketio import emit

def handle_connect():
    """Handle a new connection."""
    print("Client connected")
    emit('connected', {'message': 'Connection established'})

def handle_disconnect():
    """Handle a disconnect."""
    print("Client disconnected")

def send_kline_data(socketio, kline_data):
    """Emit kline data to the front-end."""
    socketio.emit('kline_data', kline_data, namespace='/')

def send_buy_signal(socketio, data):
    """Emit a buy signal to the front-end."""
    socketio.emit('buy_signal', data, namespace='/')

def send_sell_signal(socketio, data):
    """Emit a sell signal to the front-end."""
    socketio.emit('sell_signal', data, namespace='/')

def register_socketio_events(socketio):
    """Register socket events with the SocketIO instance."""
    socketio.on_event('connect', handle_connect)
    socketio.on_event('disconnect', handle_disconnect)
