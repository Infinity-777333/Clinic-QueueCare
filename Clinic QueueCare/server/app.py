"""
server/app.py
Main application entry point for QueueCare (First Review Version).
Configures Flask, CORS, Sessions, SocketIO, API routes, and serves client assets.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS

from websocket import socketio, init_websocket_events
from routes import api
from database import init_db

# Initialize SQLite Database (idempotent, ensures tables and default settings exist)
init_db()

# Load environment variables
dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=dotenv_path)

CLIENT_DIR = (Path(__file__).parent.parent / 'client').resolve()

app = Flask(__name__, static_folder=str(CLIENT_DIR))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'queuecare-default-insecure-dev-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Allow CORS for external origins and local network clients
CORS(app, supports_credentials=True, origins="*")

# Register REST API
app.register_blueprint(api)

# Initialize Socket.IO
socketio.init_app(app, cors_allowed_origins="*")
init_websocket_events(socketio)


# ==================================================
# STATIC CLIENT SERVING
# Allows running the full app with a single command:
# python app.py
# ==================================================

@app.route('/')
def serve_index():
    return send_from_directory(str(CLIENT_DIR), 'index.html')

@app.route('/<path:filename>')
def serve_client_file(filename):
    target = CLIENT_DIR / filename
    if target.is_file():
        return send_from_directory(str(CLIENT_DIR), filename)
    # Default fallback to index.html for patient views
    return send_from_directory(str(CLIENT_DIR), 'index.html')


@app.errorhandler(404)
def not_found(e):
    return jsonify({"success": False, "error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"success": False, "error": "An internal server error occurred."}), 500


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    print("=" * 60)
    print("  CLINIC QUEUECARE - Smart Clinic Queue Management System")
    print("  First Review Version (In-Memory Engine)")
    print(f"  Server listening on http://{host}:{port}")
    print(f"  Serving client from: {CLIENT_DIR}")
    print("=" * 60)
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
