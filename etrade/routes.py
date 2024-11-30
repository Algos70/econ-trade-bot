from flask import Blueprint, jsonify, request
from threading import Thread
from .services import trade_with_timeout
import asyncio
from etrade.extensions import socketio
api = Blueprint('api', __name__)

trade_state = {'running': False}
trade_parameters = {'longterm_sma':20, 'shortterm_sma':8, 'rsi_period':8, 'bb_lenght':20, 'rsi_oversold':30, 'rsi_overbought':70, 'symbol':'BTCUSDT'}
trade_task = None

@api.route('/info', methods=['GET'])
def get_info():
    """Example endpoint to check API status."""
    return jsonify({'message': 'API is working'})

@api.route('/start-trade', methods=['POST'])
def start_trade():
    """Endpoint to start trading."""
    global trade_task, trade_state

    if trade_state['running']:
        return jsonify({'status': 'error', 'message': 'Trade already running'}), 400
    # Extract parameters from the incoming request
    incoming_data = request.json
    if incoming_data:
        # Update trade parameters if provided
        trade_parameters.update(incoming_data)

    def run_trade():
        """Run trade logic in a separate thread."""
        trade_state['running'] = True
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(trade_with_timeout(trade_state, trade_parameters, socketio))
        except Exception as e:
            print(f"Error during trading: {e}")
        finally:
            trade_state['running'] = False

    trade_task = Thread(target=run_trade)
    trade_task.start()

    return jsonify({'status': 'success', 'message': 'Trade started'})

@api.route('/update-trade-parameters', methods=['POST'])
def update_trade_parameters():
    """Endpoint to update trade parameters."""
    global trade_parameters

    # Extract incoming data from the request
    incoming_data = request.json

    if not incoming_data:
        return jsonify({'status': 'error', 'message': 'No parameters provided'}), 400

    # Update the trade_parameters dictionary with the incoming data
    trade_parameters.update(incoming_data)

    # Return the updated trade parameters
    return jsonify({'status': 'success', 'message': 'Trade parameters updated', 'trade_parameters': trade_parameters})


@api.route('/stop-trade', methods=['POST'])
def stop_trade():
    """Endpoint to stop trading."""
    global trade_state

    if not trade_state['running']:
        return jsonify({'status': 'error', 'message': 'No trade running'}), 400

    trade_state['running'] = False
    return jsonify({'status': 'success', 'message': 'Trade stopped'})


def register_routes(app):
    """Register API routes with the Flask app."""
    app.register_blueprint(api, url_prefix='/api')
