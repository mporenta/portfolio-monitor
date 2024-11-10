from flask import Flask, jsonify, render_template, redirect, url_for, request
from db import init_db, fetch_latest_pnl_data, fetch_latest_positions_data, fetch_latest_trades_data
import logging
import signal
from flask_cors import CORS
from werkzeug import *
from werkzeug.serving import is_running_from_reloader
import os

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

app = Flask(__name__)
CORS(app)
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
    try:
        logger.info("Home route accessed, rendering dashboard.")
        return render_template('tbot_dashboard.html')
    except Exception as e:
        logger.error(f"Error in home route: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to render the dashboard'}), 500

@app.route('/api/positions', methods=['GET'])
def get_positions():
    try:
        logger.info("API call to /api/positions")
        positions = fetch_latest_positions_data()
        logger.info("Successfully fetched positions data.")
        return jsonify({'status': 'success', 'data': {'active_positions': positions}})
    except Exception as e:
        logger.error(f"Error fetching positions: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch positions data'}), 500

@app.route('/api/current-pnl', methods=['GET'])
def get_current_pnl():
    try:
        logger.info("API call to /api/current-pnl")
        data = fetch_latest_pnl_data()
        logger.info("Successfully fetched current PnL data.")
        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        logger.error(f"Error fetching current PnL: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch current PnL data'}), 500

@app.route('/api/trades', methods=['GET'])
def get_trades():
    try:
        logger.info("API call to /api/trades")
        trades = fetch_latest_trades_data()
        logger.info("Successfully fetched trades data.")
        return jsonify({'status': 'success', 'data': {'trades': trades}})
    except Exception as e:
        logger.error(f"Error fetching trades: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch trades data'}), 500

def run_flask_app():
    app.run(host='/', port=5001, use_reloader=False)

if __name__ == '__main__':
    try:
        logger.info("Starting Flask app.")
        run_flask_app()
    
    except Exception as e:
        logger.error(f"Error starting Flask app: {str(e)}")
