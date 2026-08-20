import re
from flask import Blueprint, request, jsonify, g
from email_validator import validate_email, EmailNotValidError

from app.extensions import db, limiter
from app.models import User, Role
from app.utils.auth import hash_password, verify_password, create_token_pair, login_required, decode_token

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

PASSWORD_MIN_LEN = 8


def _validate_registration(data):
    errors = {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()

    try:
        validate_email(email)
    except EmailNotValidError:
        errors["email"] = "Enter a valid email address."

    if len(password) < PASSWORD_MIN_LEN:
        errors["password"] = f"Password must be at least {PASSWORD_MIN_LEN} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        errors["password"] = "Password must include at least one letter and one number."

    if not full_name:
        errors["full_name"] = "Full name is required."

    return email, password, full_name, errors


@bp.post("/register")
@limiter.limit("10 per hour")
def register():
    data = request.get_json(silent=True) or {}
    email, password, full_name, errors = _validate_registration(data)
    if errors:
        return jsonify({"errors": errors}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"errors": {"email": "An account with this email already exists."}}), 409

    user = User(email=email, password_hash=hash_password(password), full_name=full_name, role=Role.USER.value)
    db.session.add(user)
    db.session.commit()

    access, refresh = create_token_pair(user)
    return jsonify({"user": user.to_public_dict(), "access_token": access, "refresh_token": refresh}), 201


@bp.post("/login")
@limiter.limit("20 per hour")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        return jsonify({"error": "Invalid email or password."}), 401
    if not user.is_active:
        return jsonify({"error": "This account has been disabled."}), 403

    access, refresh = create_token_pair(user)
    return jsonify({"user": user.to_public_dict(), "access_token": access, "refresh_token": refresh}), 200


@bp.post("/refresh")
def refresh():
    data = request.get_json(silent=True) or {}
    token = data.get("refresh_token")
    if not token:
        return jsonify({"error": "refresh_token is required"}), 400
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise ValueError("wrong token type")
    except Exception:
        return jsonify({"error": "Invalid or expired refresh token"}), 401

    user = User.query.get(payload["sub"])
    if not user or not user.is_active:
        return jsonify({"error": "User not found or inactive"}), 401

    access, new_refresh = create_token_pair(user)
    return jsonify({"access_token": access, "refresh_token": new_refresh}), 200


@bp.post("/logout")
@login_required
def logout():
    # Stateless JWT: logout is enforced client-side by discarding tokens.
    # For hard server-side revocation, add a token-blacklist table keyed by jti.
    return jsonify({"message": "Logged out."}), 200


@bp.get("/me")
@login_required
def me():
    return jsonify({"user": g.current_user.to_public_dict()}), 200
