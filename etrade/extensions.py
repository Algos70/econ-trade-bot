"""
This module contains the extensions for the econ-trade-bot API.
"""

from flask_socketio import SocketIO

socketio = SocketIO(
    async_mode="threading",
    cors_allowed_origins=["http://127.0.0.1:5173"],
    ping_timeout=60,
    ping_interval=25,
    manage_session=False,
)
