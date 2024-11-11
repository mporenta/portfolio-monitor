#app.py
from flask import Flask, jsonify, render_template, redirect, url_for, request
from db import init_db, fetch_latest_pnl_data, fetch_latest_positions_data, fetch_latest_trades_data
import logging
from waitress import serve
import signal
from flask_cors import CORS
from werkzeug import *
from werkzeug.serving import is_running_from_reloader
import os
from dotenv import load_dotenv
load_dotenv()

# Initialize the database to ensure tables are created
init_db()

# Set up logging
log_file_path = os.path.join(os.path.dirname(__file__), 'db.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()  # Optional: to also output logs to the console
    ]
)

logger = logging.getLogger(__name__)
PORT = int(os.getenv("PNL_HTTPS_PORT", "5001"))
app = Flask(__name__)
CORS(app)
PNL_MONITOR_URL = os.getenv('PNL_MONITOR_URL', 'http://pnl-monitor:5001')
# Add this to handle clean shutdowns
def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server()
    return 'Server shutting down...'

@app.route('/', methods=['GET'])
def home():
    return render_template('tbot_dashboard.html')

@app.route('/api/positions', methods=['GET'])
def get_positions():
    try:
        response = requests.get(f"{PNL_MONITOR_URL}/api/positions")
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/current-pnl', methods=['GET'])
def get_current_pnl():
    try:
        response = requests.get(f"{PNL_MONITOR_URL}/api/current-pnl")
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/trades', methods=['GET'])
def get_trades():
    try:
        response = requests.get(f"{PNL_MONITOR_URL}/api/trades")
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
def str2bool(value):
    """Convert string to boolean, accepting various common string representations"""
    value = value.lower()
    if value in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif value in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError(f'Invalid boolean value: {value}')
def create_app():
    """Factory function to create the app with consistent configuration"""
    return app
if __name__ == "__main__":
    production = str2bool(os.getenv("TBOT_PRODUCTION", "False"))
    
    if production:
        serve(app, host="0.0.0.0", port=PORT)
    else:
        app.run(debug=True, host="0.0.0.0", port=PORT)
else:
    # This ensures the port is set correctly when running with 'flask run'
    app.config['ENV'] = os.getenv('FLASK_ENV', 'development')
    app.config['DEBUG'] = not str2bool(os.getenv("TBOT_PRODUCTION", "False"))
