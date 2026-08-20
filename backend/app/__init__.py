from flask import Flask, jsonify
import os

from app.config import Config
from app.extensions import db, cors, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    cors.init_app(
        app,
        resources={
            r"/api/*": {
                "origins": app.config["FRONTEND_ORIGIN"]
            }
        },
    )
    limiter.init_app(app)

    from app.routes.auth_routes import bp as auth_bp
    from app.routes.generate_routes import bp as generate_bp
    from app.routes.favorite_routes import bp as favorite_bp
    from app.routes.plan_routes import bp as plan_bp
    from app.routes.admin_routes import bp as admin_bp
    from app.routes.payment_routes import bp as payment_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(favorite_bp)
    app.register_blueprint(plan_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payment_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found."}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error."}), 500

    with app.app_context():
        db.create_all()
        _run_lightweight_migrations()
        _ensure_default_plans()
        _ensure_admin_user()

    return app


def _run_lightweight_migrations():
    """
    db.create_all() only creates missing tables.
    It does not modify existing table columns.

    For SQLite, newly introduced nullable columns are added manually.
    Existing data is preserved.
    """

    if db.engine.dialect.name != "sqlite":
        return

    from sqlalchemy import text

    with db.engine.connect() as conn:

        existing_cols = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(generations)")
            )
        }

        if "advanced_brief" not in existing_cols:
            conn.execute(
                text(
                    "ALTER TABLE generations "
                    "ADD COLUMN advanced_brief JSON"
                )
            )
            conn.commit()

        name_cols = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(generated_names)")
            )
        }

        if "brand_intelligence" not in name_cols:
            conn.execute(
                text(
                    "ALTER TABLE generated_names "
                    "ADD COLUMN brand_intelligence JSON"
                )
            )
            conn.commit()

        fav_cols = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(favorites)")
            )
        }

        for col_name, col_type in [
            ("brand_story", "TEXT"),
            ("taglines", "JSON"),
            ("notes", "TEXT"),
            ("selected_logo", "TEXT"),
        ]:
            if col_name not in fav_cols:
                conn.execute(
                    text(
                        f"ALTER TABLE favorites "
                        f"ADD COLUMN {col_name} {col_type}"
                    )
                )
                conn.commit()

        user_cols = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(users)")
            )
        }

        if "stripe_customer_id" not in user_cols:
            conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN stripe_customer_id VARCHAR(255)"
                )
            )
            conn.commit()


def _ensure_default_plans():
    from app.models import Plan

    free_defaults = {
        "trademark_screening": True,
        "domain_screening": True,
        "logo_generations_per_month": 3,
        "comparisons_per_month": 5,
        "refinements_per_month": 10,
        "brand_intelligence_per_month": 15,
        "tagline_generation_per_month": 15,
    }

    pro_defaults = {
        "trademark_screening": True,
        "domain_screening": True,
        "priority_ranking": True,
        "logo_generations_per_month": None,
        "comparisons_per_month": None,
        "refinements_per_month": None,
        "brand_intelligence_per_month": None,
        "tagline_generation_per_month": None,
    }

    free = Plan.query.filter_by(code="free").first()

    if not free:
        db.session.add(
            Plan(
                code="free",
                name="Free",
                names_per_generation=25,
                monthly_generation_limit=5,
                price_cents=0,
                currency="INR",
                billing_period="monthly",
                features=free_defaults,
            )
        )
    else:
        _backfill_plan_features(
            free,
            free_defaults
        )

    pro = Plan.query.filter_by(code="pro").first()

    if not pro:
        db.session.add(
            Plan(
                code="pro",
                name="Pro",
                names_per_generation=50,
                monthly_generation_limit=None,
                price_cents=None,
                currency="INR",
                billing_period="monthly",
                features=pro_defaults,
            )
        )
    else:
        _backfill_plan_features(
            pro,
            pro_defaults
        )

    db.session.commit()


def _backfill_plan_features(plan, defaults):
    """
    Adds newly introduced feature keys without
    overwriting existing admin customizations.
    """

    current = dict(plan.features or {})
    changed = False

    for key, val in defaults.items():

        if key not in current:
            current[key] = val
            changed = True

    if changed:
        plan.features = current


def _ensure_admin_user():
    """
    Creates or promotes the configured admin user.

    The credentials are read from environment variables.
    No admin password is hard-coded in source code.
    """

    from app.models import User, Role
    from app.utils.auth import hash_password

    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    # Do nothing if admin credentials are not configured.
    if not admin_email or not admin_password:
        return

    admin_email = admin_email.strip().lower()

    if not admin_email:
        return

    user = User.query.filter_by(
        email=admin_email
    ).first()

    if user:
        # Existing user → promote to admin.
        user.role = Role.ADMIN.value

    else:
        # User does not exist → create admin.
        user = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            full_name="Admin",
            role=Role.ADMIN.value,
        )

        db.session.add(user)

    db.session.commit()