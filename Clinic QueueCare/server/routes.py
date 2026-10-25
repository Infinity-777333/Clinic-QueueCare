"""
server/routes.py
Centralized REST API blueprint for QueueCare.
Implements endpoints for Public, Patient, Auth, Doctor, and Receptionist roles.
Enforces strict server-side validation and role-based authorization.
"""

import re
from flask import Blueprint, request, jsonify, session
from auth import (
    authenticate_user,
    login_user,
    logout_user,
    get_current_user,
    login_required,
    role_required
)
from data import (
    get_clinic_settings,
    update_clinic_settings,
    get_queue_state,
    get_all_tokens,
    get_token_by_id,
    get_token_by_number,
    get_tokens_by_ids,
    get_queue_history,
    search_bookings
)
from queue import (
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
from websocket import (
    broadcast_queue_update,
    broadcast_booking_created,
    broadcast_settings_update
)

api = Blueprint('api', __name__, url_prefix='/api')

@api.before_request
def synchronize_daily_expiration():
    """Ensures past-day waiting/serving tokens are automatically expired on data access."""
    auto_expire_previous_days_bookings()

NAME_REGEX = re.compile(r"^[A-Za-z\s]{3,50}$")
MOBILE_REGEX = re.compile(r"^\d{10}$")

def validate_patient_input(name, mobile):
    """Validates patient name and mobile number according to project specs."""
    if not name or not isinstance(name, str):
        return False, "Please enter a valid patient name."
    name_clean = name.strip()
    if not (3 <= len(name_clean) <= 50) or not NAME_REGEX.match(name_clean):
        return False, "Patient name must be 3-50 characters long and contain letters and spaces only."
        
    if not mobile or not isinstance(mobile, str):
        return False, "Please enter a valid 10-digit mobile number."
    mobile_clean = mobile.strip()
    if not MOBILE_REGEX.match(mobile_clean):
        return False, "Mobile number must be exactly 10 numeric digits."
        
    return True, (name_clean, mobile_clean)


# ==================================================
# PUBLIC & OVERVIEW ENDPOINTS
# ==================================================

@api.route('/clinic/status', methods=['GET'])
def get_clinic_status():
    """Returns high-level clinic status for Patient Home."""
    settings = get_clinic_settings()
    state = get_queue_state()
    return jsonify({
        "success": True,
        "clinic_name": settings.get("clinic_name"),
        "doctor_name": settings.get("doctor_name"),
        "doctor_specialization": settings.get("doctor_specialization"),
        "clinic_start_time": settings.get("clinic_start_time"),
        "clinic_end_time": settings.get("clinic_end_time"),
        "current_token": state.get("current_token"),
        "total_tokens": state.get("total_tokens"),
        "booking_status": state.get("booking_status"),
        "consultation_status": state.get("consultation_status")
    })

@api.route('/queue', methods=['GET'])
def get_queue():
    """Returns complete real-time queue payload."""
    return jsonify({
        "success": True,
        "data": get_full_queue_payload()
    })

@api.route('/bookings', methods=['POST'])
def book_token_public():
    """Creates a patient token booking from the public website."""
    data = request.get_json() or {}
    name = data.get("patient_name")
    mobile = data.get("patient_mobile")
    
    valid, res = validate_patient_input(name, mobile)
    if not valid:
        return jsonify({"success": False, "error": res}), 400
        
    name_clean, mobile_clean = res
    token, err = create_booking(name_clean, mobile_clean, source="Patient")
    if err:
        return jsonify({"success": False, "error": err}), 400
        
    broadcast_booking_created(token)
    return jsonify({
        "success": True,
        "message": f"Token #{token['token_number']} booked successfully.",
        "booking": token,
        "clinic": get_clinic_settings()
    }), 201

@api.route('/bookings/<identifier>', methods=['GET'])
def get_booking_details(identifier):
    """Fetches details for a single token by ID or token number."""
    token = get_token_by_id(identifier)
    if not token and identifier.isdigit():
        token = get_token_by_number(int(identifier))
        
    if not token:
        return jsonify({"success": False, "error": "Booking not found."}), 404
        
    return jsonify({
        "success": True,
        "booking": token,
        "clinic": get_clinic_settings()
    })


# ==================================================
# PATIENT ENDPOINTS
# ==================================================

@api.route('/my-bookings', methods=['GET'])
def get_my_bookings():
    """
    Returns authoritative live statuses for all token IDs or numbers
    associated with the patient's browser local storage.
    """
    ids_str = request.args.get('ids', '')
    if not ids_str:
        return jsonify({"success": True, "bookings": []})
        
    id_list = [i.strip() for i in ids_str.split(',') if i.strip()]
    bookings = get_tokens_by_ids(id_list)
    
    # Sort with newest bookings first (date, session, token)
    bookings.sort(key=lambda x: (x.get("booking_date", ""), x.get("queue_session", 1), x.get("token_number", 0)), reverse=True)
    return jsonify({
        "success": True,
        "bookings": bookings,
        "clinic": get_clinic_settings()
    })

@api.route('/queue/active-tokens', methods=['GET'])
def get_active_tokens():
    """
    Returns only currently active queue tokens (Waiting / Serving)
    for the current clinic day and active queue session.
    Excludes old, expired, completed, or previous-day tokens.
    """
    ids_str = request.args.get('ids', '')
    id_list = [i.strip() for i in ids_str.split(',') if i.strip()] if ids_str else None
    data = get_active_queue_tokens(ids=id_list)
    state = get_queue_state()
    settings = get_clinic_settings()
    return jsonify({
        "success": True,
        "active_tokens": data["active_tokens"],
        "user_tokens": data["user_tokens"],
        "queue_state": state,
        "clinic": settings
    })

@api.route('/queue/progress/<identifier>', methods=['GET'])
def get_queue_progress(identifier):
    """Calculates live queue position and progress for a patient's token by booking ID or token number."""
    progress, err = get_patient_progress(identifier)
    if err:
        return jsonify({"success": False, "error": err}), 404
        
    return jsonify({
        "success": True,
        "progress": progress,
        "clinic": get_clinic_settings()
    })


# ==================================================
# AUTHENTICATION ENDPOINTS
# ==================================================

@api.route('/auth/doctor/login', methods=['POST'])
def doctor_login():
    """Authenticates doctor account."""
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")
    
    user = authenticate_user(username, password)
    if not user or user.get("role") != "doctor":
        return jsonify({"success": False, "error": "Invalid doctor credentials."}), 401
        
    login_user(user)
    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": user
    })

@api.route('/auth/reception/login', methods=['POST'])
def reception_login():
    """Authenticates receptionist account."""
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")
    
    user = authenticate_user(username, password)
    if not user or user.get("role") != "receptionist":
        return jsonify({"success": False, "error": "Invalid receptionist credentials."}), 401
        
    login_user(user)
    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": user
    })

@api.route('/auth/logout', methods=['POST'])
def logout():
    """Logs out the current staff member."""
    logout_user()
    return jsonify({"success": True, "message": "Logged out successfully."})

@api.route('/auth/me', methods=['GET'])
def get_current_session():
    """Returns the authenticated user or 401."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return jsonify({"success": True, "user": user})


# ==================================================
# DOCTOR ONLY ENDPOINTS
# ==================================================

@api.route('/doctor/dashboard', methods=['GET'])
@role_required('doctor')
def doctor_dashboard():
    """Provides full data set for doctor dashboard."""
    payload = get_full_queue_payload()
    tokens = get_all_tokens()
    # Sort all tokens by token_number ascending
    tokens.sort(key=lambda x: x["token_number"])
    return jsonify({
        "success": True,
        "dashboard": payload,
        "today_patients": tokens,
        "user": get_current_user()
    })

@api.route('/doctor/next', methods=['POST'])
@role_required('doctor')
def doctor_call_next():
    """Calls next patient from the waiting queue."""
    ok, new_state, next_tok = call_next_patient()
    broadcast_queue_update()
    return jsonify({
        "success": True,
        "message": f"Called Token #{next_tok['token_number']}" if next_tok else "All waiting patients completed.",
        "queue_state": new_state,
        "serving_patient": next_tok
    })

@api.route('/doctor/complete', methods=['POST'])
@role_required('doctor')
def doctor_complete_patient():
    """Marks the currently serving patient as completed."""
    ok, res = complete_current_patient()
    if not ok:
        return jsonify({"success": False, "error": res}), 400
    broadcast_queue_update()
    return jsonify({
        "success": True,
        "message": "Patient consultation completed.",
        "queue_state": res
    })

@api.route('/doctor/undo', methods=['POST'])
@role_required('doctor')
def doctor_undo():
    """Reverts the last queue action."""
    ok, res = undo_last_action()
    if not ok:
        return jsonify({"success": False, "error": res}), 400
    broadcast_queue_update()
    return jsonify({
        "success": True,
        "message": "Previous queue action undone successfully.",
        "queue_state": res
    })

@api.route('/doctor/bookings/open', methods=['POST'])
@role_required('doctor')
def doctor_open_bookings():
    """Opens online token bookings."""
    ok, new_state = set_booking_status("OPEN")
    broadcast_queue_update()
    return jsonify({
        "success": True,
        "message": "Bookings are now OPEN.",
        "booking_status": "OPEN"
    })

@api.route('/doctor/bookings/close', methods=['POST'])
@role_required('doctor')
def doctor_close_bookings():
    """Closes online token bookings."""
    ok, new_state = set_booking_status("CLOSED")
    broadcast_queue_update()
    return jsonify({
        "success": True,
        "message": "Bookings are now CLOSED.",
        "booking_status": "CLOSED"
    })

@api.route('/doctor/consultation-status', methods=['POST'])
@role_required('doctor')
def doctor_set_consultation_status():
    """Rejects arbitrary manual consultation status changes; status is driven automatically by queue workflow."""
    return jsonify({
        "success": False,
        "error": "Consultation status is automatically managed by queue actions."
    }), 400

@api.route('/doctor/queue/reset', methods=['POST'])
@role_required('doctor')
def doctor_reset_queue():
    """Transactionally resets daily queue to start a fresh session from Token 1, expiring any remaining waiting tokens."""
    data = request.get_json(silent=True) or {}
    expire_waiting = data.get("expire_waiting", True)
    ok, res = reset_queue_session(expire_waiting=expire_waiting)
    if not ok:
        return jsonify({"success": False, "error": res}), 400
    broadcast_queue_update()
    return jsonify({
        "success": True,
        "message": res,
        "queue_state": get_queue_state()
    })

@api.route('/doctor/history', methods=['GET'])
@role_required('doctor')
def doctor_history():
    """Returns queue action history, optionally filtered by date and session."""
    date_filter = request.args.get('date', '').strip() or None
    session_filter = request.args.get('session', '').strip() or None
    history = get_queue_history(today_str=date_filter, session=session_filter)
    return jsonify({
        "success": True,
        "history": history
    })

@api.route('/doctor/settings', methods=['GET'])
@role_required('doctor')
def doctor_get_settings():
    """Returns clinic settings for editing."""
    return jsonify({
        "success": True,
        "settings": get_clinic_settings()
    })

@api.route('/doctor/settings', methods=['PUT'])
@role_required('doctor')
def doctor_update_settings():
    """Updates clinic configuration and updates all active references."""
    data = request.get_json() or {}
    
    # Validation
    clinic_name = data.get("clinic_name", "").strip()
    doctor_name = data.get("doctor_name", "").strip()
    doctor_specialization = data.get("doctor_specialization", "").strip()
    clinic_start_time = data.get("clinic_start_time", "").strip()
    clinic_end_time = data.get("clinic_end_time", "").strip()
    daily_token_limit = data.get("daily_token_limit")
    
    if not clinic_name or not doctor_name:
        return jsonify({"success": False, "error": "Clinic name and Doctor name are required."}), 400
        
    try:
        daily_token_limit = int(daily_token_limit)
        if daily_token_limit < 1:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Daily token limit must be a positive integer."}), 400
        
    updated = update_clinic_settings({
        "clinic_name": clinic_name,
        "doctor_name": doctor_name,
        "doctor_specialization": doctor_specialization,
        "clinic_start_time": clinic_start_time,
        "clinic_end_time": clinic_end_time,
        "daily_token_limit": daily_token_limit
    })
    
    # Update current doctor session full_name
    current_u = get_current_user()
    if current_u:
        current_u["full_name"] = doctor_name
        current_u["specialization"] = doctor_specialization
        session['user'] = current_u
        
    broadcast_settings_update(updated)
    return jsonify({
        "success": True,
        "message": "Clinic settings updated successfully.",
        "settings": updated
    })


# ==================================================
# RECEPTIONIST ENDPOINTS
# ==================================================

@api.route('/reception/today', methods=['GET'])
@role_required('receptionist', 'doctor')
def reception_today_bookings():
    """Returns today's bookings for reception dashboard."""
    tokens = get_all_tokens()
    tokens.sort(key=lambda x: x["token_number"])
    state = get_queue_state()
    settings = get_clinic_settings()
    return jsonify({
        "success": True,
        "tokens": tokens,
        "queue_state": state,
        "clinic": settings,
        "user": get_current_user()
    })

@api.route('/reception/walk-in', methods=['POST'])
@role_required('receptionist', 'doctor')
def reception_walk_in_booking():
    """Registers a walk-in patient at the clinic desk."""
    data = request.get_json() or {}
    name = data.get("patient_name")
    mobile = data.get("patient_mobile")
    
    valid, res = validate_patient_input(name, mobile)
    if not valid:
        return jsonify({"success": False, "error": res}), 400
        
    name_clean, mobile_clean = res
    token, err = create_booking(name_clean, mobile_clean, source="Walk-in")
    if err:
        return jsonify({"success": False, "error": err}), 400
        
    broadcast_booking_created(token)
    return jsonify({
        "success": True,
        "message": f"Walk-in Token #{token['token_number']} issued.",
        "booking": token,
        "clinic": get_clinic_settings()
    }), 201

@api.route('/reception/phone', methods=['POST'])
@role_required('receptionist', 'doctor')
def reception_phone_booking():
    """Registers a phone-in patient at the clinic desk."""
    data = request.get_json() or {}
    name = data.get("patient_name")
    mobile = data.get("patient_mobile")
    
    valid, res = validate_patient_input(name, mobile)
    if not valid:
        return jsonify({"success": False, "error": res}), 400
        
    name_clean, mobile_clean = res
    token, err = create_booking(name_clean, mobile_clean, source="Phone")
    if err:
        return jsonify({"success": False, "error": err}), 400
        
    broadcast_booking_created(token)
    return jsonify({
        "success": True,
        "message": f"Phone Token #{token['token_number']} issued.",
        "booking": token,
        "clinic": get_clinic_settings()
    }), 201

@api.route('/reception/search', methods=['GET'])
@role_required('receptionist', 'doctor')
def reception_search():
    """Filters today's bookings by Patient Name, Mobile, or Token Number."""
    q = request.args.get('q', '').strip()
    results = search_bookings(q)
    return jsonify({"success": True, "results": results})
