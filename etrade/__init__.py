from flask import Flask
from etrade.routes import register_routes
from etrade.config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Register routes
    register_routes(app)

    return app
