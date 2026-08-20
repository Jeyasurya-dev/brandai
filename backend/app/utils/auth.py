import jwt
import bcrypt
from functools import wraps
from datetime import datetime, timezone
from flask import request, jsonify, current_app, g

from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(user: User, expires_delta, token_type="access"):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "role": user.role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def create_token_pair(user: User):
    access = create_token(user, current_app.config["JWT_ACCESS_TOKEN_EXPIRES"], "access")
    refresh = create_token(user, current_app.config["JWT_REFRESH_TOKEN_EXPIRES"], "refresh")
    return access, refresh


def decode_token(token: str):
    return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])


def _extract_token():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


def login_required(fn):
    """Validates JWT and attaches the authenticated user to flask.g.current_user.
    This check happens purely server-side; it is never trusted from the client."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({"error": "Authentication required"}), 401
        try:
            payload = decode_token(token)
            if payload.get("type") != "access":
                return jsonify({"error": "Invalid token type"}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        user = User.query.get(payload["sub"])
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 401

        g.current_user = user
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    """Enforces ADMIN role strictly on the backend. This is the authoritative
    check — the frontend's own role-based UI hiding is cosmetic only."""

    @wraps(fn)
    def inner(*args, **kwargs):
        if g.current_user.role != "ADMIN":
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)

    return login_required(inner)
