from flask import Flask, jsonify, render_template
from flask_cors import CORS
import logging
from pathlib import Path
import sqlite3
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "pnl_monitor.db"

def get_latest_data():
    """Get latest PnL and position data from database"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get latest PnL data
            cursor.execute('''
                SELECT * FROM account_pnl 
                ORDER BY timestamp DESC 
                LIMIT 1
            ''')
            pnl_data = dict(cursor.fetchone() or {})
            
            # Get latest positions
            cursor.execute('''
                SELECT * FROM positions 
                WHERE timestamp = (
                    SELECT MAX(timestamp) FROM positions
                )
            ''')
            positions = [dict(row) for row in cursor.fetchall()]
            
            return pnl_data, positions
    except Exception as e:
        logger.error(f"Database error: {e}")
        return {}, []

@app.route('/')
def index():
    return render_template('pnl_dashboard.html')

@app.route('/api/current-pnl/<account_id>')
def get_current_pnl(account_id):
    """Get current PnL summary"""
    try:
        pnl_data, _ = get_latest_data()
        if pnl_data:
            return jsonify({
                'status': 'success',
                'data': {
                    'daily_pnl': pnl_data.get('daily_pnl', 0.0),
                    'total_realized_pnl': pnl_data.get('total_realized_pnl', 0.0),
                    'total_unrealized_pnl': pnl_data.get('total_unrealized_pnl', 0.0),
                    'net_liquidation': pnl_data.get('net_liquidation', 0.0),
                    'risk_amount': pnl_data.get('risk_amount', 0.0),
                    'timestamp': pnl_data.get('timestamp', datetime.now().isoformat())
                }
            })
    except Exception as e:
        logger.error(f"Error getting PnL data: {e}")
    
    return jsonify({
        'status': 'warning',
        'message': 'No data available',
        'data': {
            'daily_pnl': 0.0,
            'total_realized_pnl': 0.0,
            'total_unrealized_pnl': 0.0,
            'net_liquidation': 0.0,
            'risk_amount': 0.0,
            'timestamp': datetime.now().isoformat()
        }
    })

@app.route('/api/positions/<account_id>')
def get_positions(account_id):
    """Get current positions"""
    try:
        _, positions = get_latest_data()
        
        active_positions = [p for p in positions if p.get('position', 0) != 0]
        closed_positions = [p for p in positions if p.get('position', 0) == 0]
        
        return jsonify({
            'status': 'success',
            'data': {
                'active_positions': active_positions,
                'closed_positions': closed_positions,
                'timestamp': datetime.now().isoformat()
            }
        })
    except Exception as e:
        logger.error(f"Error getting position data: {e}")
    
    return jsonify({
        'status': 'warning',
        'message': 'No position data available',
        'data': {
            'active_positions': [],
            'closed_positions': [],
            'timestamp': datetime.now().isoformat()
        }
    })

@app.route('/api/status')
def get_status():
    """Get data collection status"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM account_pnl 
                WHERE timestamp > datetime('now', '-5 minutes')
            ''')
            recent_updates = cursor.fetchone()[0]
            
            return jsonify({
                'status': 'success' if recent_updates > 0 else 'warning',
                'message': 'Data collection active' if recent_updates > 0 else 'No recent updates',
                'updates_last_5min': recent_updates
            })
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

if __name__ == '__main__':
    logger.info(f"Starting web service, database path: {DB_PATH}")
    app.run(debug=True, port=5001)
