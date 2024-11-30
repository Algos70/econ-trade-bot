from flask import Flask
from etrade.routes import register_routes
from etrade.config import Config
from etrade.extensions import socketio

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    socketio.init_app(app)

    register_routes(app)

    return app
