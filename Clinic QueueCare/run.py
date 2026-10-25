"""
run.py
Convenience root launcher for Clinic QueueCare.
Executes the server located in the server/ directory.
"""

import sys
import os
from pathlib import Path

# Add server directory to Python path
SERVER_DIR = Path(__file__).parent / 'server'
sys.path.insert(0, str(SERVER_DIR))

# Switch working directory to server for relative paths
os.chdir(SERVER_DIR)

from app import app, socketio
import os as std_os

if __name__ == '__main__':
    host = std_os.getenv('HOST', '0.0.0.0')
    port = int(std_os.getenv('PORT', 5000))
    print("=" * 60)
    print("  CLINIC QUEUECARE - Smart Clinic Queue Management System")
    print("  First Review Version (In-Memory Engine)")
    print(f"  Server listening on http://{host}:{port}")
    print("=" * 60)
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
