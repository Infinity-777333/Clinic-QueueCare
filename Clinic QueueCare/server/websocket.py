"""
server/websocket.py
WebSocket / Socket.IO management for real-time queue updates.
Emits events to all connected Patient, Doctor, and Receptionist clients.
"""

from flask_socketio import SocketIO, emit
from queue import get_full_queue_payload
from data import get_clinic_settings

# Initialize SocketIO instance with permissive CORS for local network and mobile devices
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")

def init_websocket_events(sio):
    """Registers basic connection and subscription events."""
    @sio.on('connect')
    def handle_connect():
        # Send initial full queue payload upon connection
        payload = get_full_queue_payload()
        emit('queue:update', payload)

    @sio.on('disconnect')
    def handle_disconnect():
        pass

    @sio.on('request:queue')
    def handle_request_queue():
        payload = get_full_queue_payload()
        emit('queue:update', payload)

def broadcast_queue_update():
    """Broadcasts updated queue state to all connected clients."""
    payload = get_full_queue_payload()
    socketio.emit('queue:update', payload)

def broadcast_booking_created(booking_data):
    """Notifies all clients of a newly created booking."""
    socketio.emit('booking:created', booking_data)
    broadcast_queue_update()

def broadcast_settings_update(settings_data):
    """Notifies all clients of modified clinic settings."""
    socketio.emit('settings:update', settings_data)
    broadcast_queue_update()
