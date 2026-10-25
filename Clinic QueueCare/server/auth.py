"""
server/auth.py
Authentication and Role-Based Authorization service for QueueCare.
Supports bcrypt hashing, Flask HTTP-only session cookies, and role checks.
"""

from functools import wraps
from flask import session, jsonify, request
import bcrypt
from data import get_user_by_username

def authenticate_user(username, password):
    """
    Validates username and password.
    Returns user dict (without password hash) on success, or None on failure.
    """
    if not username or not password:
        return None

    user = get_user_by_username(username.strip())
    if not user:
        return None

    stored_hash = user.get("password_hash")
    if not stored_hash:
        return None

    # Verify bcrypt password
    try:
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
            safe_user = {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "full_name": user["full_name"],
                "specialization": user.get("specialization", "")
            }
            return safe_user
    except Exception:
        return None

    return None

def login_user(user):
    """Stores user information in the secure HTTP session."""
    session['user'] = user
    session.permanent = True

def logout_user():
    """Clears the session."""
    session.pop('user', None)

def get_current_user():
    """Returns the currently logged-in user from the session, or None."""
    return session.get('user')

def login_required(f):
    """Decorator ensuring that a user is authenticated."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({
                "success": False,
                "error": "Please login to continue."
            }), 401
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    """Decorator ensuring that the logged-in user has one of the allowed roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({
                    "success": False,
                    "error": "Please login to continue."
                }), 401
            
            if user.get("role") not in allowed_roles:
                return jsonify({
                    "success": False,
                    "error": "You are not authorized to perform this action."
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
