from flask import Blueprint, jsonify, request

api = Blueprint('api', __name__)

# Example GET endpoint
@api.route('/info', methods=['GET'])
def get_info():
    return jsonify({'message': 'This is a sample endpoint'})

def register_routes(app):
    app.register_blueprint(api, url_prefix='/api')