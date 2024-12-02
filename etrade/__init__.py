"""
This module contains the main application for the econ-trade-bot API.
"""

# pylint: disable=import-error
from flask import Flask
# pylint: disable=import-error
from flask_cors import CORS
from etrade.routes import register_routes
from etrade.config import Config
from etrade.extensions import socketio


def create_app():
    """Create the Flask app."""
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    app.config.from_object(Config)

    socketio.init_app(app)
    register_routes(app)

    return app
