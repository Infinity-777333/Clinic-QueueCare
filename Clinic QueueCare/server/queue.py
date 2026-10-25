"""
server/queue.py
Queue business logic and bridge for QueueCare.
Re-exports Python standard library queue classes to prevent third-party library conflicts,
and delegates queue operations to transaction-safe SQLite database procedures in database.py.
"""

import os
import sys
import importlib.util

# Re-export Python standard library queue classes so third-party libraries (e.g. engineio)
# that do 'import queue' remain fully functional if this module is on sys.path
try:
    _stdlib_queue_path = os.path.join(os.path.dirname(os.__file__), 'queue.py')
    if os.path.exists(_stdlib_queue_path):
        _spec = importlib.util.spec_from_file_location('_std_queue', _stdlib_queue_path)
        _std_q = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_std_q)
        Queue = _std_q.Queue
        LifoQueue = _std_q.LifoQueue
        PriorityQueue = _std_q.PriorityQueue
        Empty = _std_q.Empty
        Full = _std_q.Full
        SimpleQueue = getattr(_std_q, 'SimpleQueue', None)
except Exception:
    pass

from database import (
    create_booking,
    call_next_patient,
    complete_current_patient,
    undo_last_action,
    reset_queue_session,
    auto_expire_previous_days_bookings,
    get_active_queue_tokens,
    set_booking_status,
    set_consultation_status,
    get_full_queue_payload,
    get_patient_progress
)
