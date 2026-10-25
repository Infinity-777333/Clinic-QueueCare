"""
server/data.py
SQLite-backed data access interface for QueueCare.
Delegates all data operations to server/database.py, making SQLite the single
authoritative source of truth while maintaining backward-compatible function signatures.
"""

from database import (
    get_clinic_settings,
    update_clinic_settings,
    get_queue_state,
    update_queue_state,
    get_current_session_number,
    get_user_by_username,
    get_all_tokens,
    get_all_today_tokens,
    get_token_by_id,
    get_token_by_number,
    get_tokens_by_ids,
    update_token,
    reset_queue_session,
    auto_expire_previous_days_bookings,
    get_active_queue_tokens,
    get_queue_history,
    add_queue_history_record,
    get_undo_stack_size,
    is_undo_available,
    search_bookings,
    db_lock as data_lock
)
