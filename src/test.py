# initialize our Flask application
import logging
from logging import getLogger, DEBUG
from flask_cors import CORS
import os
import requests
import tbot
from flask import Flask, request, jsonify, render_template, Response, redirect

from commons import VERSION_NUMBER, LOG_LOCATION
from components.actions.base.action import am
from components.events.base.event import em
from components.logs.log_event import LogEvent
from components.schemas.trading import Order, Position
from utils.log import get_logger
from utils.register import register_action, register_event, register_link
from distutils.util import strtobool

# register actions, events, links
from settings import REGISTERED_ACTIONS, REGISTERED_EVENTS, REGISTERED_LINKS
from waitress import serve

registered_actions = [register_action(action) for action in REGISTERED_ACTIONS]
registered_events = [register_event(event) for event in REGISTERED_EVENTS]
registered_links = [register_link(link, em, am) for link in REGISTERED_LINKS]

app = Flask(__name__)

# configure logging
logger = get_logger(__name__)

# Enable CORS
CORS(app)

app.add_url_rule("/", view_func=tbot.get_main)
app.add_url_rule("/orders", view_func=tbot.get_orders)
app.add_url_rule("/alerts", view_func=tbot.get_alerts)
app.add_url_rule("/ngrok", view_func=tbot.get_ngrok)
app.add_url_rule("/errors", view_func=tbot.get_errors)
app.add_url_rule("/tbot", view_func=tbot.get_tbot)
app.add_url_rule("/orders/data", view_func=tbot.get_orders_data)
app.add_url_rule("/alerts/data", view_func=tbot.get_alerts_data)
app.add_url_rule("/errors/data", view_func=tbot.get_errors_data)
app.add_url_rule("/tbot/data", view_func=tbot.get_tbot_data)
app.teardown_appcontext(tbot.close_connection)

schema_list = {"order": Order().as_json(), "position": Position().as_json()}

@app.route('/portfolio')
def portfolio():
    """Proxy requests to the portfolio monitoring service"""
    try:
        # Proxy the request to the portfolio service
        response = requests.get('http://localhost:5001')
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['content-type']
        )
    except requests.RequestException as e:
        # Handle case where portfolio service is not available
        return render_template(
            'service_error.html',
            error_message="Portfolio service is currently unavailable",
            service_name="Portfolio Monitor"
        ), 503

# Add these routes to proxy the API calls
@app.route('/api/current-pnl/<account_id>')
def proxy_pnl(account_id):
    """Proxy PnL data requests"""
    try:
        response = requests.get(f'http://localhost:5001/api/current-pnl/{account_id}')
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['content-type']
        )
    except requests.RequestException:
        return jsonify({
            'status': 'error',
            'message': 'Portfolio service unavailable'
        }), 503

@app.route('/api/positions/<account_id>')
def proxy_positions(account_id):
    """Proxy position data requests"""
    try:
        response = requests.get(f'http://localhost:5001/api/positions/{account_id}')
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['content-type']
        )
    except requests.RequestException:
        return jsonify({
            'status': 'error',
            'message': 'Portfolio service unavailable'
        }), 503

# Add static file proxy if needed
@app.route('/portfolio/static/<path:filename>')
def proxy_portfolio_static(filename):
    """Proxy static files from portfolio service"""
    try:
        response = requests.get(f'http://localhost:5001/static/{filename}')
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['content-type']
        )
    except requests.RequestException:
        return 'Static resource unavailable', 404
@app.route("/dashboard", methods=["GET"])
def dashboard():
    if request.method == 'GET':

        # check if gui key file exists
        try:
            with open('.gui_key', 'r') as key_file:
                gui_key = key_file.read().strip()
                # check that the gui key from file matches the gui key from request
                if gui_key == request.args.get('guiKey', None):
                    pass
                else:
                    return 'Access Denied', 401

        # if gui key file does not exist, the tvwb.py did not start gui in closed mode
        except FileNotFoundError:
            logger.warning('GUI key file not found. Open GUI mode detected.')

        # serve the dashboard
        action_list = am.get_all()
        return render_template(
            template_name_or_list='dashboard.html',
            schema_list=schema_list,
            action_list=action_list,
            event_list=registered_events,
            version=VERSION_NUMBER
        )


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        jsondic_data = request.get_json(force=True, silent=True)
        if not jsondic_data:
            logger.warning(f"Invalid JSON response {jsondic_data}")
            return Response(status=415)
        elif not jsondic_data.get("key"):
            logger.warning(f"Missing Key in the response {jsondic_data}")
            return Response(status=415)
        logger.debug(f"Request Data: {jsondic_data}")
        triggered_events = []
        for event in em.get_all():
            if event.webhook:
                if event.key == jsondic_data["key"]:
                    event.trigger(data=jsondic_data)
                    triggered_events.append(event.name)

        if not triggered_events:
            logger.warning(f"No events triggered for webhook request {jsondic_data}")
        else:
            logger.info(f"Triggered events: {triggered_events}")
            if logger.level <= logging.INFO:
                logger.info(f"client IP: {request.remote_addr}")
                if request.environ.get("HTTP_X_FORWARDED_FOR") is None:
                    logger.info(request.environ["REMOTE_ADDR"])
                else:
                    logger.info(request.environ["HTTP_X_FORWARDED_FOR"])

    return Response(status=200)


@app.route("/logs", methods=["GET"])
def get_logs():
    if request.method == 'GET':
        log_file = open(LOG_LOCATION, 'r')
        logs = [LogEvent().from_line(log) for log in log_file.readlines()]
        return jsonify([log.as_json() for log in logs])


@app.route("/event/active", methods=["POST"])
def activate_event():
    if request.method == 'POST':
        # get query parameters
        event_name = request.args.get('event', None)

        # if event name is not provided, or cannot be found, 404
        if event_name is None:
            return Response(f'Event name cannot be empty ({event_name})', status=404)
        try:
            event = em.get(event_name)
        except ValueError:
            return Response(f'Cannot find event with name: {event_name}', status=404)

        # set event to active or inactive, depending on current state
        event.active = request.args.get('active', True) == 'true'
        logger.info(f'Event {event.name} active set to: {event.active}, via POST request')
        return {'active': event.active}




if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if not strtobool(os.getenv("TBOT_PRODUCTION", "False")) else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler()]  # Ensure logs are sent to stdout
    )
    
    logger = logging.getLogger(__name__)

    try:
        port = int(os.getenv("TVWB_HTTPS_PORT", "5000"))
        is_production = strtobool(os.getenv("TBOT_PRODUCTION", "False"))
        
        if is_production:
            logger.info("Starting in production mode.")
            serve(app, host="0.0.0.0", port=port)
        else:
            logger.info("Starting in development mode with debug.")
            app.run(debug=True, host="0.0.0.0", port=port)
    except Exception as e:
        logger.exception("An error occurred while running the Flask app.")
