import uuid
import enum
from datetime import datetime
from app.extensions import db


def gen_uuid():
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class TrademarkRisk(str, enum.Enum):
    LOW = "Low Risk"
    MEDIUM = "Medium Risk"
    HIGH = "High Risk"
    SEARCH_FAILED = "Search Failed"
    NEEDS_REVIEW = "Needs Manual Review"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), nullable=False, default=Role.USER.value)
    is_active = db.Column(db.Boolean, default=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subscriptions = db.relationship("Subscription", backref="user", lazy=True)
    generations = db.relationship("Generation", backref="user", lazy=True)
    favorites = db.relationship("Favorite", backref="user", lazy=True)

    def to_public_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    code = db.Column(db.String(50), unique=True, nullable=False)  # e.g. "free", "pro"
    name = db.Column(db.String(100), nullable=False)
    names_per_generation = db.Column(db.Integer, nullable=False, default=25)
    monthly_generation_limit = db.Column(db.Integer, nullable=True)  # None = unlimited
    price_cents = db.Column(db.Integer, nullable=True)  # set via admin, never hard-coded in logic
    currency = db.Column(db.String(10), default="USD")
    billing_period = db.Column(db.String(20), default="monthly")
    features = db.Column(db.JSON, default=dict)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "names_per_generation": self.names_per_generation,
            "monthly_generation_limit": self.monthly_generation_limit,
            "price_cents": self.price_cents,
            "currency": self.currency,
            "billing_period": self.billing_period,
            "features": self.features or {},
            "is_active": self.is_active,
        }


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    plan_id = db.Column(db.String(36), db.ForeignKey("plans.id"), nullable=False)
    status = db.Column(db.String(20), default="active")  # active, cancelled, expired
    provider = db.Column(db.String(50), nullable=True)  # e.g. "stripe"
    provider_subscription_id = db.Column(db.String(255), nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    plan = db.relationship("Plan")


class Generation(db.Model):
    __tablename__ = "generations"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    business_description = db.Column(db.Text, nullable=False)
    industry = db.Column(db.String(120), nullable=True)
    inspirations = db.Column(db.JSON, default=list)  # list of strings
    style_tags = db.Column(db.JSON, default=list)  # e.g. ["Premium", "Futuristic"]
    advanced_brief = db.Column(db.JSON, nullable=True)  # optional advanced naming controls, see routes/generate_routes.py
    requested_count = db.Column(db.Integer, default=25)
    candidate_pool_size = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default="Generating...")  # pending, completed, failed
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    names = db.relationship("GeneratedName", backref="generation", lazy=True, cascade="all, delete-orphan")


class GeneratedName(db.Model):
    __tablename__ = "generated_names"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    generation_id = db.Column(db.String(36), db.ForeignKey("generations.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    meaning = db.Column(db.Text, nullable=True)
    inspiration_used = db.Column(db.String(255), nullable=True)
    style_alignment = db.Column(db.Text, nullable=True)
    brandability_score = db.Column(db.Float, nullable=True)  # 0-100
    rank = db.Column(db.Integer, nullable=True)

    trademark_status = db.Column(db.String(30), default=TrademarkRisk.NEEDS_REVIEW.value)
    trademark_details = db.Column(db.JSON, nullable=True)

    domain_status = db.Column(db.JSON, nullable=True)  # {"com": "available"/"taken"/"unavailable", ...}

    # AI-derived heuristic scores (memorability, pronunciation, etc.) —
    # explicitly NOT trademark/domain data. Computed lazily on first request
    # and cached here so repeat views don't re-call the AI provider.
    brand_intelligence = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "meaning": self.meaning,
            "inspiration_used": self.inspiration_used,
            "style_alignment": self.style_alignment,
            "brandability_score": self.brandability_score,
            "rank": self.rank,
            "trademark_status": self.trademark_status,
            "trademark_details": self.trademark_details,
            "domain_status": self.domain_status,
            "brand_intelligence": self.brand_intelligence,
        }


class Favorite(db.Model):
    __tablename__ = "favorites"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    generated_name_id = db.Column(db.String(36), db.ForeignKey("generated_names.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Brand Workspace fields — upgrades a plain Favorite into a lightweight
    # Brand Kit without touching the original favoriting behavior. All
    # nullable/optional: a favorite with none of these set behaves exactly
    # like the original Favorite always did. Trademark screening, domain
    # status, and Brand DNA (AI intelligence) are intentionally NOT
    # duplicated here — they're read live from the linked GeneratedName
    # instead, so the workspace never shows stale/diverged copies of that
    # real data.
    brand_story = db.Column(db.Text, nullable=True)
    taglines = db.Column(db.JSON, nullable=True)  # list of strings
    notes = db.Column(db.Text, nullable=True)
    selected_logo = db.Column(db.Text, nullable=True)  # one data:image/png;base64,... the user chose to keep

    generated_name = db.relationship("GeneratedName")

    __table_args__ = (db.UniqueConstraint("user_id", "generated_name_id", name="uq_user_favorite"),)


class TrademarkSearch(db.Model):
    __tablename__ = "trademark_searches"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    generated_name_id = db.Column(db.String(36), db.ForeignKey("generated_names.id"), nullable=True)
    query_name = db.Column(db.String(255), nullable=False)
    provider = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(30), nullable=False)
    raw_response = db.Column(db.JSON, nullable=True)
    requested_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminSetting(db.Model):
    __tablename__ = "admin_settings"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.JSON, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    actor_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FeatureUsage(db.Model):
    """One row per successful use of a metered premium feature (logo
    generation, name comparison, name refinement, brand intelligence).
    Logged only AFTER a call succeeds — a failed/errored request never
    consumes a user's monthly quota. Used for both plan enforcement
    (generate_routes.py) and admin analytics (admin_routes.py)."""
    __tablename__ = "feature_usage"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    feature = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_feature_usage_user_feature_created", "user_id", "feature", "created_at"),
    )
