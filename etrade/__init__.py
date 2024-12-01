from flask import Flask
from etrade.routes import register_routes
from etrade.config import Config
from etrade.extensions import socketio
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    app.config.from_object(Config)

    socketio.init_app(app)
    register_routes(app)

    return app
