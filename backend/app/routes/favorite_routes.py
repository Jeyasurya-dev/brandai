from flask import Blueprint, request, jsonify, g, send_file

from app.extensions import db, limiter
from app.models import Favorite, GeneratedName, Generation
from app.utils.auth import login_required
from app.services.ai_service import AIService, AIServiceError
from app.services.metering import user_plan, check_feature_limit, log_feature_usage

import io
import base64
import zipfile

bp = Blueprint("favorites", __name__, url_prefix="/api/favorites")

# A base64 PNG data URI this size covers a generous logo (well beyond what
# Imagen typically returns); anything larger is rejected rather than
# silently stored, to keep the favorites table from being abused as blob
# storage.
MAX_LOGO_DATA_URI_LENGTH = 3_000_000
MAX_TAGLINES = 10
MAX_TAGLINE_LENGTH = 100
MAX_TEXT_FIELD_LENGTH = 2000


def _favorite_to_dict(f):
    return {
        "id": f.id,
        "created_at": f.created_at.isoformat(),
        "name": f.generated_name.to_dict() if f.generated_name else None,
        "brand_story": f.brand_story,
        "taglines": f.taglines,
        "notes": f.notes,
        "selected_logo": f.selected_logo,
    }


def _validate_workspace_fields(data):
    """Never trust the frontend: validate types and cap lengths. Returns
    (cleaned_dict, error_message_or_None). Only keys actually present in
    `data` are validated/returned, so PATCH can update a subset of fields."""
    cleaned = {}

    if "brand_story" in data:
        val = data.get("brand_story")
        if val is not None and not isinstance(val, str):
            return None, "brand_story must be a string."
        cleaned["brand_story"] = (val or "").strip()[:MAX_TEXT_FIELD_LENGTH] or None

    if "notes" in data:
        val = data.get("notes")
        if val is not None and not isinstance(val, str):
            return None, "notes must be a string."
        cleaned["notes"] = (val or "").strip()[:MAX_TEXT_FIELD_LENGTH] or None

    if "taglines" in data:
        val = data.get("taglines")
        if val is not None and not isinstance(val, list):
            return None, "taglines must be a list of strings."
        if val is None:
            cleaned["taglines"] = None
        else:
            items = [str(t).strip()[:MAX_TAGLINE_LENGTH] for t in val if str(t).strip()][:MAX_TAGLINES]
            cleaned["taglines"] = items or None

    if "selected_logo" in data:
        val = data.get("selected_logo")
        if val is not None:
            if not isinstance(val, str) or not val.startswith("data:image/"):
                return None, "selected_logo must be a data:image/... URI."
            if len(val) > MAX_LOGO_DATA_URI_LENGTH:
                return None, "selected_logo is too large."
        cleaned["selected_logo"] = val or None

    return cleaned, None


@bp.get("")
@login_required
def list_favorites():
    user = g.current_user
    favorites = Favorite.query.filter_by(user_id=user.id).order_by(Favorite.created_at.desc()).all()
    return jsonify({"favorites": [_favorite_to_dict(f) for f in favorites]}), 200


@bp.post("")
@login_required
def add_favorite():
    """Adds a name to Favorites — unchanged core behavior. Optionally also
    accepts Brand Workspace fields (e.g. selected_logo) so a single call
    from the Logo Generator's "Save to workspace" button can both favorite
    a name AND attach a logo in one request, whether or not it was already
    favorited."""
    user = g.current_user
    data = request.get_json(silent=True) or {}
    generated_name_id = data.get("generated_name_id")
    if not generated_name_id:
        return jsonify({"error": "generated_name_id is required."}), 400

    name = (
        GeneratedName.query.join(Generation, GeneratedName.generation_id == Generation.id)
        .filter(GeneratedName.id == generated_name_id, Generation.user_id == user.id)
        .first()
    )
    if not name:
        return jsonify({"error": "Name not found."}), 404

    cleaned, error = _validate_workspace_fields(data)
    if error:
        return jsonify({"error": error}), 400

    existing = Favorite.query.filter_by(user_id=user.id, generated_name_id=generated_name_id).first()
    if existing:
        # Already favorited — still apply any workspace fields sent this
        # time (e.g. attaching a logo to an already-favorited name) rather
        # than silently ignoring them.
        changed = False
        for key, val in cleaned.items():
            if val is not None:
                setattr(existing, key, val)
                changed = True
        if changed:
            db.session.commit()
        return jsonify({"message": "Already favorited.", "id": existing.id, "favorite": _favorite_to_dict(existing)}), 200

    favorite = Favorite(user_id=user.id, generated_name_id=generated_name_id, **cleaned)
    db.session.add(favorite)
    db.session.commit()
    return (
        jsonify({"message": "Added to favorites.", "id": favorite.id, "favorite": _favorite_to_dict(favorite)}),
        201,
    )


@bp.patch("/<favorite_id>")
@login_required
def update_favorite(favorite_id):
    """Brand Workspace edit: update brand_story / taglines / notes /
    selected_logo on an existing favorite. Ownership enforced the same way
    remove_favorite already did — only the owning user can touch it."""
    user = g.current_user
    favorite = Favorite.query.filter_by(id=favorite_id, user_id=user.id).first()
    if not favorite:
        return jsonify({"error": "Favorite not found."}), 404

    data = request.get_json(silent=True) or {}
    cleaned, error = _validate_workspace_fields(data)
    if error:
        return jsonify({"error": error}), 400
    if not cleaned:
        return jsonify({"error": "No valid workspace fields provided."}), 400

    for key, val in cleaned.items():
        setattr(favorite, key, val)
    db.session.commit()

    return jsonify({"message": "Workspace updated.", "favorite": _favorite_to_dict(favorite)}), 200


@bp.delete("/<favorite_id>")
@login_required
def remove_favorite(favorite_id):
    user = g.current_user
    favorite = Favorite.query.filter_by(id=favorite_id, user_id=user.id).first()
    if not favorite:
        return jsonify({"error": "Favorite not found."}), 404
    db.session.delete(favorite)
    db.session.commit()
    return jsonify({"message": "Removed from favorites."}), 200


@bp.post("/<favorite_id>/taglines")
@login_required
@limiter.limit("15 per hour")
def generate_taglines(favorite_id):
    """AI Tagline Generator for a Brand Workspace entry: 5 short taglines
    for this saved name, using its business context and (if the user wrote
    one) their own brand story. Purely a drafting aid — nothing is
    auto-saved; the frontend lets the user review and add whichever
    taglines they want via the existing PATCH /favorites/<id> endpoint."""
    user = g.current_user
    favorite = Favorite.query.filter_by(id=favorite_id, user_id=user.id).first()
    if not favorite or not favorite.generated_name:
        return jsonify({"error": "Favorite not found."}), 404

    ai_service = AIService.from_app_config()
    if not ai_service.is_configured():
        return (
            jsonify(
                {
                    "error": "Tagline generation is currently unavailable: the server has no Gemini AI "
                    "provider configured. Set GEMINI_API_KEY in the backend .env to enable it."
                }
            ),
            503,
        )

    plan = user_plan(user)
    limited = check_feature_limit(user, plan, "tagline_generation", "tagline_generation_per_month")
    if limited:
        return limited

    name_row = favorite.generated_name
    generation = name_row.generation

    try:
        taglines = ai_service.generate_taglines(
            name=name_row.name,
            meaning=name_row.meaning,
            business_description=generation.business_description if generation else None,
            brand_story=favorite.brand_story,
        )
    except AIServiceError as e:
        return jsonify({"error": str(e)}), 502

    log_feature_usage(user.id, "tagline_generation")

    return jsonify({"favorite_id": favorite.id, "name": name_row.name, "taglines": taglines}), 200


@bp.get("/<favorite_id>/export")
@login_required
def export_brand_kit(favorite_id):
    """Brand Kit export: bundles everything in a Brand Workspace entry
    (name, meaning, real trademark/domain screening, Brand DNA if
    assessed, brand story, taglines, notes, and the saved logo if any)
    into a single downloadable ZIP. Read-only — doesn't call any AI/image
    provider, just packages data that's already on the record, so it's not
    metered."""
    user = g.current_user
    favorite = Favorite.query.filter_by(id=favorite_id, user_id=user.id).first()
    if not favorite or not favorite.generated_name:
        return jsonify({"error": "Favorite not found."}), 404

    n = favorite.generated_name
    lines = [f"BRAND KIT — {n.name}", "=" * (12 + len(n.name)), ""]
    lines.append(f"Meaning: {n.meaning or 'Not provided'}")
    lines.append(f"Inspiration used: {n.inspiration_used or 'None'}")
    lines.append(f"Brandability score: {round(n.brandability_score or 0)}/100")
    lines.append("")

    lines.append(f"Trademark screening: {n.trademark_status or 'Not Screened'}")
    if n.trademark_details:
        if n.trademark_details.get("jurisdiction"):
            lines.append(f"  Jurisdiction: {n.trademark_details['jurisdiction']}")
        if n.trademark_details.get("explanation"):
            lines.append(f"  {n.trademark_details['explanation']}")
        if n.trademark_details.get("disclaimer"):
            lines.append(f"  {n.trademark_details['disclaimer']}")
    lines.append("")

    if n.domain_status:
        lines.append("Domain availability:")
        for tld, status in n.domain_status.items():
            lines.append(f"  .{tld}: {status}")
        lines.append("")

    if n.brand_intelligence:
        bi = n.brand_intelligence
        lines.append("Brand DNA (AI-derived heuristic estimate — not verified data, not a guarantee):")
        for key in ["memorability", "pronunciation", "distinctiveness", "premium_feel", "global_usability", "domain_potential"]:
            if key in bi:
                lines.append(f"  {key.replace('_', ' ').title()}: {round(bi[key])}/100")
        if bi.get("rationale"):
            lines.append(f"  Rationale: {bi['rationale']}")
        lines.append("")
    else:
        lines.append("Brand DNA: not yet assessed.")
        lines.append("")

    if favorite.brand_story:
        lines.append("Brand story:")
        lines.append(f"  {favorite.brand_story}")
        lines.append("")

    if favorite.taglines:
        lines.append("Taglines:")
        for t in favorite.taglines:
            lines.append(f"  - {t}")
        lines.append("")

    if favorite.notes:
        lines.append("Notes:")
        lines.append(f"  {favorite.notes}")
        lines.append("")

    lines.append(f"Saved to workspace: {favorite.created_at.isoformat()}")
    lines.append("")
    lines.append(
        "This brand kit was generated by Brandmark AI. Trademark and domain "
        "screening is preliminary automated screening only, not legal advice — "
        "confirm through the relevant official registry and qualified counsel "
        "before adopting this brand."
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("brand-summary.txt", "\n".join(lines))
        if favorite.selected_logo and favorite.selected_logo.startswith("data:image/"):
            try:
                _header, b64data = favorite.selected_logo.split(",", 1)
                zf.writestr("logo.png", base64.b64decode(b64data))
            except Exception:
                pass  # a malformed saved logo shouldn't block the rest of the export
    buf.seek(0)

    safe_name = "".join(c if c.isalnum() else "-" for c in n.name).strip("-").lower() or "brand"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_name}-brand-kit.zip",
    )
