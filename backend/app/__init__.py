from flask import Flask, jsonify

from app.config import Config
from app.extensions import db, cors, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["FRONTEND_ORIGIN"]}})
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

    return app


def _run_lightweight_migrations():
    """
    db.create_all() only creates missing tables — it never alters an
    existing table's columns. This project has no Alembic migration setup,
    so for the common case (sqlite) we add any newly-introduced nullable
    columns by hand, in place, without touching existing rows. This never
    drops or renames a column, so existing data is preserved.

    For non-sqlite databases, this is a no-op — add columns manually there.
    """
    if db.engine.dialect.name != "sqlite":
        return

    from sqlalchemy import text

    with db.engine.connect() as conn:
        existing_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(generations)"))}
        if "advanced_brief" not in existing_cols:
            conn.execute(text("ALTER TABLE generations ADD COLUMN advanced_brief JSON"))
            conn.commit()

        name_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(generated_names)"))}
        if "brand_intelligence" not in name_cols:
            conn.execute(text("ALTER TABLE generated_names ADD COLUMN brand_intelligence JSON"))
            conn.commit()

        fav_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(favorites)"))}
        for col_name, col_type in [
            ("brand_story", "TEXT"),
            ("taglines", "JSON"),
            ("notes", "TEXT"),
            ("selected_logo", "TEXT"),
        ]:
            if col_name not in fav_cols:
                conn.execute(text(f"ALTER TABLE favorites ADD COLUMN {col_name} {col_type}"))
                conn.commit()

        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if "stripe_customer_id" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(255)"))
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
                currency="USD",
                billing_period="monthly",
                features=free_defaults,
            )
        )
    else:
        _backfill_plan_features(free, free_defaults)

    pro = Plan.query.filter_by(code="pro").first()
    if not pro:
        db.session.add(
            Plan(
                code="pro",
                name="Pro",
                names_per_generation=50,
                monthly_generation_limit=None,
                price_cents=None,
                currency="USD",
                billing_period="monthly",
                features=pro_defaults,
            )
        )
    else:
        _backfill_plan_features(pro, pro_defaults)

    db.session.commit()


def _backfill_plan_features(plan, defaults):
    """Adds any newly-introduced feature keys to an existing plan's
    `features` JSON without overwriting anything an admin may have already
    customized — only fills in keys that don't exist yet, never changes or
    removes an existing value."""
    current = dict(plan.features or {})
    changed = False
    for key, val in defaults.items():
        if key not in current:
            current[key] = val
            changed = True
    if changed:
        plan.features = current
