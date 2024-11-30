from flask import Blueprint, jsonify, request
from threading import Thread
from .services import trade_with_timeout
import asyncio
from etrade.extensions import socketio

api = Blueprint('api', __name__)

# Dictionary to track state for each trading pair
trade_states = {
    'ETHUSDT': {'running': False},
    'BTCUSDT': {'running': False},
    'AVAXUSDT': {'running': False},
    'SOLUSDT': {'running': False},
    'RENDERUSDT': {'running': False},
    'FETUSDT': {'running': False}
}

# Dictionary to store thread objects
trade_tasks = {}

# Default parameters for each trading pair
default_parameters = {
    'longterm_sma': 20,
    'shortterm_sma': 8,
    'rsi_period': 8,
    'bb_lenght': 20,
    'rsi_oversold': 30,
    'rsi_overbought': 70
}

# Dictionary to store parameters for each trading pair
trade_parameters = {
    symbol: default_parameters.copy() | {'symbol': symbol}
    for symbol in trade_states.keys()
}

@api.route('/start-trade', methods=['POST'])
def start_trade():
    """Endpoint to start trading for all pairs."""
    incoming_data = request.json or {}

    # Start trading for each symbol that isn't already running
    started_pairs = []
    error_pairs = []

    for symbol in trade_states.keys():
        if trade_states[symbol]['running']:
            error_pairs.append(symbol)
            continue

        # Update parameters if provided
        if incoming_data:
            trade_parameters[symbol].update(incoming_data)

        def create_trade_runner(symbol):
            def run_trade():
                """Run trade logic in a separate thread."""
                trade_states[symbol]['running'] = True
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        trade_with_timeout(
                            trade_states[symbol],
                            trade_parameters[symbol],
                            socketio
                        )
                    )
                except Exception as e:
                    print(f"Error during trading {symbol}: {e}")
                finally:
                    trade_states[symbol]['running'] = False

            return run_trade

        trade_tasks[symbol] = Thread(target=create_trade_runner(symbol))
        trade_tasks[symbol].start()
        started_pairs.append(symbol)

    response = {
        'status': 'success',
        'started_pairs': started_pairs,
    }
    
    if error_pairs:
        response['errors'] = f"Already running: {', '.join(error_pairs)}"

    return jsonify(response)

@api.route('/stop-trade', methods=['POST'])
def stop_trade():
    """Endpoint to stop trading for all pairs or specific pairs."""
    symbols = request.json.get('symbols') if request.json else None
    
    if symbols is None:
        # Stop all trading pairs
        symbols = list(trade_states.keys())

    stopped_pairs = []
    error_pairs = []

    for symbol in symbols:
        if symbol not in trade_states:
            error_pairs.append(f"Invalid symbol: {symbol}")
            continue
            
        if not trade_states[symbol]['running']:
            error_pairs.append(f"Not running: {symbol}")
            continue

        trade_states[symbol]['running'] = False
        stopped_pairs.append(symbol)

    response = {
        'status': 'success',
        'stopped_pairs': stopped_pairs,
    }
    
    if error_pairs:
        response['errors'] = error_pairs

    return jsonify(response)

@api.route('/trading-status', methods=['GET'])
def get_trading_status():
    """Endpoint to get the status of all trading pairs."""
    return jsonify({
        'status': 'success',
        'trading_status': {
            symbol: {
                'running': state['running'],
                'parameters': trade_parameters[symbol]
            }
            for symbol, state in trade_states.items()
        }
    })

@api.route('/update-trade-parameters', methods=['POST'])
def update_trade_parameters():
    """Endpoint to update trade parameters for specific symbols."""
    incoming_data = request.json

    if not incoming_data:
        return jsonify({'status': 'error', 'message': 'No parameters provided'}), 400

    symbols = incoming_data.get('symbols', list(trade_states.keys()))
    parameters = incoming_data.get('parameters', {})

    if not parameters:
        return jsonify({'status': 'error', 'message': 'No parameters provided'}), 400

    updated_pairs = []
    for symbol in symbols:
        if symbol in trade_parameters:
            trade_parameters[symbol].update(parameters)
            updated_pairs.append(symbol)

    return jsonify({
        'status': 'success',
        'message': 'Trade parameters updated',
        'updated_pairs': updated_pairs,
        'parameters': parameters
    })

def register_routes(app):
    """Register API routes with the Flask app."""
    app.register_blueprint(api, url_prefix='/api')
