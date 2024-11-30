from etrade import create_app
from etrade.extensions import socketio
from etrade.sockets import register_socketio_events

app = create_app()
register_socketio_events(socketio)

if __name__ == '__main__':
    socketio.run(app, host='127.0.0.1', port=5000)
