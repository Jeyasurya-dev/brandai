"""
One-off script to create (or promote) an admin user.
Usage:
    python seed_admin.py admin@example.com StrongPass123
"""
import sys
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import User, Role
from app.utils.auth import hash_password


def main():
    if len(sys.argv) != 3:
        print("Usage: python seed_admin.py <email> <password>")
        sys.exit(1)

    email, password = sys.argv[1].strip().lower(), sys.argv[2]
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user:
            user.role = Role.ADMIN.value
            print(f"Promoted existing user {email} to ADMIN.")
        else:
            user = User(email=email, password_hash=hash_password(password), full_name="Admin", role=Role.ADMIN.value)
            db.session.add(user)
            print(f"Created new admin user {email}.")
        db.session.commit()


if __name__ == "__main__":
    main()
