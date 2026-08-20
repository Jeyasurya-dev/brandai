from datetime import datetime

from flask import Blueprint, request, jsonify, g

from app.extensions import db, limiter
from app.models import Generation, GeneratedName, TrademarkSearch
from app.utils.auth import login_required
from app.services.ai_service import AIService, AIServiceError, REFINEMENT_DIRECTIONS
from app.services.ranking_service import quality_filter, duplicate_filter, advanced_filter, initial_rank, final_sort
from app.services.trademark_service import TrademarkService, infer_jurisdiction, LEGAL_DISCLAIMER
from app.services.domain_service import DomainService
from app.services.logo_service import LogoGenerationService, LogoGenerationError, LOGO_TYPES
from app.services.metering import user_plan, check_feature_limit, log_feature_usage

bp = Blueprint("generate", __name__, url_prefix="/api")

TRADEMARK_DISCLAIMER = LEGAL_DISCLAIMER

# ---- Advanced naming controls: server-side validation ----
# field -> max character length
ADVANCED_TEXT_FIELDS = {
    "naming_for": 100,
    "target_audience": 200,
    "target_market": 200,
    "naming_language": 150,
    "name_length": 50,
    "name_structure": 80,
    "desired_meaning": 500,
    "brand_story": 800,
    "future_expansion": 300,
    "five_year_vision": 500,
    "domain_preference": 150,
    "trademark_strategy": 300,
}
# field -> (max items, max chars per item)
ADVANCED_LIST_FIELDS = {
    "brand_personality": (10, 40),
    "competitors": (10, 60),
    "names_liked": (10, 40),
    "names_disliked": (10, 40),
    "words_to_include": (15, 40),
    "words_to_avoid": (15, 40),
}


def _validate_and_clean_advanced(raw):
    """Never trust the frontend: re-validate types and cap lengths here.
    Unknown keys are silently dropped. Returns {} if nothing usable was
    supplied — advanced controls are entirely optional."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("advanced must be an object.")

    cleaned = {}
    for field, max_len in ADVANCED_TEXT_FIELDS.items():
        val = raw.get(field)
        if val is None:
            continue
        val = str(val).strip()[:max_len]
        if val:
            cleaned[field] = val

    for field, (max_items, max_len) in ADVANCED_LIST_FIELDS.items():
        val = raw.get(field)
        if val is None:
            continue
        if not isinstance(val, list):
            raise ValueError(f"{field} must be a list of strings.")
        items = [str(v).strip()[:max_len] for v in val if str(v).strip()][:max_items]
        if items:
            cleaned[field] = items

    return cleaned


def _user_plan(user):
    return user_plan(user)


def _generations_used_this_month(user_id):
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return Generation.query.filter(
        Generation.user_id == user_id,
        Generation.status != "failed",
        Generation.created_at >= month_start,
    ).count()


# ---- Subscription-gated feature usage metering ----
# Server-side only, never trusts the frontend. Admins always bypass. Usage
# is logged AFTER a call succeeds, so a failed/errored request never
# consumes a user's monthly quota — checked BEFORE the (paid) AI/image
# provider call, so a request that would be rejected never burns quota
# with the provider either.
#
# The actual implementations live in app/services/metering.py, shared with
# favorite_routes.py (AI tagline generation) so there's exactly one copy of
# this logic. Thin wrappers kept here under their original names so every
# existing call site below didn't need to change.

def _check_feature_limit(user, plan, feature, feature_key):
    return check_feature_limit(user, plan, feature, feature_key)


def _log_feature_usage(user_id, feature):
    log_feature_usage(user_id, feature)


@bp.post("/generate")
@login_required
@limiter.limit("15 per hour")
def generate_names():
    user = g.current_user
    data = request.get_json(silent=True) or {}

    business_description = (data.get("business_description") or "").strip()
    industry = (data.get("industry") or "").strip() or None
    inspirations = data.get("inspirations") or []
    style_tags = data.get("style_tags") or []

    if not business_description:
        return jsonify({"error": "business_description is required."}), 400
    if not isinstance(inspirations, list):
        return jsonify({"error": "inspirations must be a list of strings."}), 400
    if not isinstance(style_tags, list):
        return jsonify({"error": "style_tags must be a list of strings."}), 400

    try:
        advanced = _validate_and_clean_advanced(data.get("advanced"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    plan = _user_plan(user)
    names_per_generation = plan.names_per_generation if plan else 25

    # Admins get unlimited access regardless of plan.
    if user.role == "ADMIN":
        names_per_generation = max(names_per_generation, 25)
    elif plan and plan.monthly_generation_limit is not None:
        used = _generations_used_this_month(user.id)
        if used >= plan.monthly_generation_limit:
            return (
                jsonify(
                    {
                        "error": f"Monthly generation limit reached for your plan ({plan.monthly_generation_limit}/mo). "
                        "Upgrade your plan or wait for next month's reset.",
                        "plan": plan.code,
                        "monthly_generation_limit": plan.monthly_generation_limit,
                        "used_this_month": used,
                    }
                ),
                403,
            )

    generation = Generation(
        user_id=user.id,
        business_description=business_description,
        industry=industry,
        inspirations=inspirations,
        style_tags=style_tags,
        advanced_brief=advanced or None,
        requested_count=names_per_generation,
        status="Generating...",
    )
    db.session.add(generation)
    db.session.commit()

    ai_service = AIService.from_app_config()
    if not ai_service.is_configured():
        generation.status = "failed"
        generation.error_message = (
            "AI provider not configured (GEMINI_API_KEY missing)."
        )
        db.session.commit()
        return (
            jsonify(
                {
                    "error": "AI name generation is currently unavailable: the server has no Gemini AI "
                    "provider configured. Set GEMINI_API_KEY in the backend .env to enable it.",
                    "generation_id": generation.id,
                }
            ),
            503,
        )

    pool_size = max(names_per_generation * 2, 50)

    try:
        candidates = ai_service.generate_candidate_pool(
            business_description, industry, inspirations, style_tags, pool_size=pool_size, advanced=advanced
        )
    except AIServiceError as e:
        generation.status = "failed"
        generation.error_message = str(e)
        db.session.commit()
        return jsonify({"error": str(e), "generation_id": generation.id}), 502

    generation.candidate_pool_size = len(candidates)

    filtered = quality_filter(candidates)
    filtered = advanced_filter(filtered, advanced)
    deduped = duplicate_filter(filtered)
    ranked = initial_rank(deduped)

    if not ranked:
        generation.status = "failed"
        generation.error_message = "No candidates survived quality/duplicate filtering."
        db.session.commit()
        return jsonify({"error": "The AI did not return usable candidates. Try adjusting your inputs.", "generation_id": generation.id}), 502

    shortlisted = ranked[: min(len(ranked), names_per_generation * 2 if len(ranked) > names_per_generation else len(ranked))]
    # Cap the shortlist that goes through screening to a sane multiple of the target count.
    shortlisted = shortlisted[: max(names_per_generation, min(len(shortlisted), names_per_generation + 15))]

    trademark_service = TrademarkService.from_app_config()
    domain_service = DomainService.from_app_config()
    jurisdiction = infer_jurisdiction(advanced)

    enriched = []
    for candidate in shortlisted:
        tm_result = trademark_service.search(candidate.name, jurisdiction=jurisdiction)
        domain_result = domain_service.check(candidate.name)

        db.session.add(
            TrademarkSearch(
                query_name=candidate.name,
                provider=tm_result.provider,
                status=tm_result.status,
                raw_response=tm_result.details,
                requested_by=user.id,
            )
        )

        enriched.append(
            {
                "name": candidate.name,
                "meaning": candidate.meaning,
                "inspiration_used": candidate.inspiration_used,
                "style_alignment": candidate.style_alignment,
                "brandability_score": candidate.brandability_score,
                "trademark_status": tm_result.status,
                "trademark_details": tm_result.details,
                "domain_status": domain_result,
            }
        )

    final_ranked = final_sort(enriched)[:names_per_generation]

    for entry in final_ranked:
        db.session.add(
            GeneratedName(
                generation_id=generation.id,
                name=entry["name"],
                meaning=entry["meaning"],
                inspiration_used=entry["inspiration_used"],
                style_alignment=entry["style_alignment"],
                brandability_score=entry["brandability_score"],
                rank=entry["rank"],
                trademark_status=entry["trademark_status"],
                trademark_details=entry["trademark_details"],
                domain_status=entry["domain_status"],
            )
        )

    generation.status = "completed"
    db.session.commit()

    saved_names = GeneratedName.query.filter_by(generation_id=generation.id).order_by(GeneratedName.rank).all()

    return (
        jsonify(
            {
                "generation_id": generation.id,
                "requested_count": names_per_generation,
                "candidate_pool_size": generation.candidate_pool_size,
                "returned_count": len(saved_names),
                "names": [n.to_dict() for n in saved_names],
                "advanced_brief": generation.advanced_brief,
                "trademark_jurisdiction": jurisdiction,
                "trademark_disclaimer": TRADEMARK_DISCLAIMER,
            }
        ),
        201,
    )


@bp.post("/brief-builder")
@login_required
@limiter.limit("20 per hour")
def build_brief():
    """AI Brief Builder — optional helper. Turns a short free-form
    description into a structured brief the user reviews/edits before it's
    (optionally) applied to the manual generate form. Does not generate
    names and does not replace the manual workflow."""
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()

    if not description:
        return jsonify({"error": "description is required."}), 400
    if len(description) > 2000:
        return jsonify({"error": "description is too long (max 2000 characters)."}), 400

    ai_service = AIService.from_app_config()
    if not ai_service.is_configured():
        return (
            jsonify(
                {
                    "error": "AI Brief Builder is currently unavailable: the server has no Gemini AI "
                    "provider configured. Set GEMINI_API_KEY in the backend .env to enable it."
                }
            ),
            503,
        )

    try:
        brief = ai_service.build_brief(description)
    except AIServiceError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"brief": brief}), 200


def _owned_name_or_none(name_id, user_id):
    """Same ownership pattern as favorites: only ever touch a
    GeneratedName that belongs to a generation owned by the requesting
    user."""
    return (
        GeneratedName.query.join(Generation, GeneratedName.generation_id == Generation.id)
        .filter(GeneratedName.id == name_id, Generation.user_id == user_id)
        .first()
    )


def _get_or_compute_intelligence(name_row, ai_service):
    """Cache-or-compute: Brand Intelligence is deterministic-ish per name,
    so we only call the AI provider once per name and persist the result.
    Raises AIServiceError if it needs to compute and the provider isn't
    available — callers decide how to surface that."""
    if name_row.brand_intelligence:
        return name_row.brand_intelligence, True  # (data, was_cached)

    business_description = name_row.generation.business_description if name_row.generation else ""
    result = ai_service.assess_brand_intelligence(name_row.name, name_row.meaning, business_description)
    name_row.brand_intelligence = result
    db.session.commit()
    return result, False


@bp.get("/names/<name_id>/intelligence")
@login_required
@limiter.limit("40 per hour")
def name_intelligence(name_id):
    """Brand Intelligence for a single generated name. Returns two clearly
    separated blocks: `ai_intelligence` (AI-derived heuristic estimate —
    memorability, pronunciation, distinctiveness, premium feel, global
    usability, domain potential, existing-brand-signals recall) and
    `real_data` (the actual trademark/domain screening already performed by
    TrademarkService/DomainService at generation time). These are never
    merged — the AI estimate is never presented as verified fact."""
    user = g.current_user
    name_row = _owned_name_or_none(name_id, user.id)
    if not name_row:
        return jsonify({"error": "Name not found."}), 404

    ai_service = AIService.from_app_config()
    if not name_row.brand_intelligence and not ai_service.is_configured():
        return (
            jsonify(
                {
                    "error": "Brand Intelligence is currently unavailable: the server has no Gemini AI "
                    "provider configured. Set GEMINI_API_KEY in the backend .env to enable it."
                }
            ),
            503,
        )

    # Only meter actual computation, never a cached re-view — a repeat look
    # at an already-assessed name costs nothing extra and shouldn't count
    # against the user's monthly quota.
    if not name_row.brand_intelligence:
        plan = _user_plan(user)
        limited = _check_feature_limit(user, plan, "brand_intelligence", "brand_intelligence_per_month")
        if limited:
            return limited

    try:
        intelligence, cached = _get_or_compute_intelligence(name_row, ai_service)
    except AIServiceError as e:
        return jsonify({"error": str(e)}), 502

    if not cached:
        _log_feature_usage(user.id, "brand_intelligence")

    return (
        jsonify(
            {
                "id": name_row.id,
                "name": name_row.name,
                "cached": cached,
                "ai_intelligence": {
                    **intelligence,
                    "label": "AI-derived heuristic estimate — not verified data, not a guarantee.",
                },
                "brandability_score": name_row.brandability_score,
                "real_data": {
                    "label": "Real screening data (see provider/status for what was actually checked).",
                    "trademark_status": name_row.trademark_status,
                    "trademark_details": name_row.trademark_details,
                    "domain_status": name_row.domain_status,
                },
            }
        ),
        200,
    )


@bp.post("/names/compare")
@login_required
@limiter.limit("15 per hour")
def compare_names():
    """Name Comparison: takes 2-6 generated_name ids (must belong to the
    requesting user) and returns each with its brandability score, real
    trademark/domain data, and AI Brand Intelligence (computed or reused
    from cache, same as the single-name endpoint) so the frontend can
    render a side-by-side table."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not (2 <= len(ids) <= 6):
        return jsonify({"error": "ids must be a list of 2 to 6 generated name IDs."}), 400

    user = g.current_user
    plan = _user_plan(user)

    limited = _check_feature_limit(user, plan, "name_comparison", "comparisons_per_month")
    if limited:
        return limited

    ai_service = AIService.from_app_config()

    results = []
    intelligence_computed = 0
    for name_id in ids:
        name_row = _owned_name_or_none(name_id, user.id)
        if not name_row:
            return jsonify({"error": f"Name not found or not accessible: {name_id}"}), 404

        entry = {
            "id": name_row.id,
            "name": name_row.name,
            "brandability_score": name_row.brandability_score,
            "trademark_status": name_row.trademark_status,
            "domain_status": name_row.domain_status,
            "ai_intelligence": None,
            "ai_intelligence_error": None,
        }

        needs_compute = not name_row.brand_intelligence
        if needs_compute:
            # Same per-name Brand Intelligence quota as the single-name
            # endpoint — but a hit quota here degrades gracefully (this
            # name just shows without AI scores) rather than aborting the
            # whole comparison.
            intel_limited = _check_feature_limit(user, plan, "brand_intelligence", "brand_intelligence_per_month")
            if intel_limited:
                entry["ai_intelligence_error"] = "Monthly Brand Intelligence limit reached for your plan."
                results.append(entry)
                continue

        try:
            if name_row.brand_intelligence or ai_service.is_configured():
                intelligence, cached = _get_or_compute_intelligence(name_row, ai_service)
                entry["ai_intelligence"] = intelligence
                if not cached:
                    intelligence_computed += 1
            else:
                entry["ai_intelligence_error"] = "Brand Intelligence unavailable: no Gemini AI provider configured."
        except AIServiceError as e:
            entry["ai_intelligence_error"] = str(e)

        results.append(entry)

    _log_feature_usage(user.id, "name_comparison")
    for _ in range(intelligence_computed):
        _log_feature_usage(user.id, "brand_intelligence")

    return jsonify({"names": results}), 200


@bp.post("/names/<generated_name_id>/refine")
@login_required
@limiter.limit("20 per hour")
def refine_name(generated_name_id):
    """Name Refinement: generates 5 alternative naming concepts derived
    from one already-generated name along a single requested direction,
    using the SAME business/inspiration/style/advanced-brief context the
    original generation used. Ownership is checked the same way as
    favorites/intelligence/comparison — a user can only refine a name that
    belongs to one of their own generations."""
    user = g.current_user
    name_row = _owned_name_or_none(generated_name_id, user.id)
    if not name_row:
        return jsonify({"error": "Name not found."}), 404

    data = request.get_json(silent=True) or {}
    direction = (data.get("direction") or "").strip()
    if direction not in REFINEMENT_DIRECTIONS:
        return (
            jsonify({"error": f"direction must be one of: {', '.join(REFINEMENT_DIRECTIONS)}"}),
            400,
        )

    generation = name_row.generation
    if not generation:
        return jsonify({"error": "Original generation context is missing for this name."}), 404

    ai_service = AIService.from_app_config()
    if not ai_service.is_configured():
        return (
            jsonify(
                {
                    "error": "Name refinement is currently unavailable: the server has no Gemini AI "
                    "provider configured. Set GEMINI_API_KEY in the backend .env to enable it."
                }
            ),
            503,
        )

    plan = _user_plan(user)
    limited = _check_feature_limit(user, plan, "name_refinement", "refinements_per_month")
    if limited:
        return limited

    try:
        candidates = ai_service.refine_name(
            business_description=generation.business_description,
            industry=generation.industry,
            inspirations=generation.inspirations or [],
            style_tags=generation.style_tags or [],
            advanced=generation.advanced_brief,
            original_name=name_row.name,
            original_meaning=name_row.meaning,
            direction=direction,
        )
    except AIServiceError as e:
        return jsonify({"error": str(e)}), 502

    _log_feature_usage(user.id, "name_refinement")

    # 5 candidates is a small, bounded number of extra provider calls, so we
    # run the SAME real trademark/domain screening pipeline used at
    # generation time rather than leaving refined candidates unscreened.
    # Never fabricated: same TrademarkService/DomainService as everywhere
    # else, same honest failure states if a provider isn't configured.
    trademark_service = TrademarkService.from_app_config()
    domain_service = DomainService.from_app_config()
    jurisdiction = infer_jurisdiction(generation.advanced_brief)

    enriched = []
    for c in candidates:
        tm_result = trademark_service.search(c["name"], jurisdiction=jurisdiction)
        domain_result = domain_service.check(c["name"])
        db.session.add(
            TrademarkSearch(
                query_name=c["name"],
                provider=tm_result.provider,
                status=tm_result.status,
                raw_response=tm_result.details,
                requested_by=user.id,
            )
        )
        enriched.append(
            {
                **c,
                "trademark_status": tm_result.status,
                "trademark_details": tm_result.details,
                "domain_status": domain_result,
            }
        )
    db.session.commit()

    return (
        jsonify(
            {
                "generated_name_id": name_row.id,
                "original_name": name_row.name,
                "direction": direction,
                "trademark_jurisdiction": jurisdiction,
                "trademark_disclaimer": TRADEMARK_DISCLAIMER,
                "names": enriched,
            }
        ),
        200,
    )


@bp.post("/names/<generated_name_id>/logo")
@login_required
@limiter.limit("10 per hour")
def generate_logo(generated_name_id):
    """AI Logo Generator: generates concept logos for one already-generated
    name. Independent LogoGenerationService (image generation), reusing the
    same GEMINI_API_KEY as everything else — no second provider/key. Same
    ownership pattern as favorites/intelligence/comparison/refine."""
    user = g.current_user
    name_row = _owned_name_or_none(generated_name_id, user.id)
    if not name_row:
        return jsonify({"error": "Name not found."}), 404

    data = request.get_json(silent=True) or {}
    logo_type = (data.get("logo_type") or "").strip()
    if logo_type not in LOGO_TYPES:
        return jsonify({"error": f"logo_type must be one of: {', '.join(LOGO_TYPES)}"}), 400

    style = str(data.get("style") or "").strip()[:150]
    color_preference = str(data.get("color_preference") or "").strip()[:150]
    brand_personality = data.get("brand_personality")
    if brand_personality is not None:
        if not isinstance(brand_personality, list):
            return jsonify({"error": "brand_personality must be a list of strings."}), 400
        brand_personality = [str(v).strip()[:40] for v in brand_personality if str(v).strip()][:10]

    try:
        count = int(data.get("count", 3))
    except (TypeError, ValueError):
        count = 3
    count = max(1, min(4, count))

    generation = name_row.generation
    logo_service = LogoGenerationService.from_app_config()
    if not logo_service.is_configured():
        return (
            jsonify(
                {
                    "error": "Logo generation is currently unavailable: the server has no Gemini AI "
                    "provider configured. Set GEMINI_API_KEY in the backend .env to enable it."
                }
            ),
            503,
        )

    plan = _user_plan(user)
    limited = _check_feature_limit(user, plan, "logo_generation", "logo_generations_per_month")
    if limited:
        return limited

    try:
        result = logo_service.generate_logos(
            brand_name=name_row.name,
            logo_type=logo_type,
            style=style or None,
            color_preference=color_preference or None,
            brand_description=generation.business_description if generation else None,
            inspiration=name_row.inspiration_used,
            brand_personality=brand_personality,
            count=count,
        )
    except LogoGenerationError as e:
        return jsonify({"error": str(e)}), 502

    _log_feature_usage(user.id, "logo_generation")

    return (
        jsonify(
            {
                "generated_name_id": name_row.id,
                "name": name_row.name,
                "logo_type": logo_type,
                "images": [f"data:image/png;base64,{b64}" for b64 in result.images_base64],
                "prompt_used": result.prompt_used,
                "note": "AI-generated concept art — review for trademark/copyright issues and refine with a "
                "designer before commercial use. Not persisted; download any you want to keep.",
            }
        ),
        200,
    )


@bp.get("/history")
@login_required
def history():
    user = g.current_user
    generations = (
        Generation.query.filter_by(user_id=user.id).order_by(Generation.created_at.desc()).limit(50).all()
    )
    result = []
    for gen in generations:
        result.append(
            {
                "id": gen.id,
                "business_description": gen.business_description,
                "industry": gen.industry,
                "inspirations": gen.inspirations,
                "style_tags": gen.style_tags,
                "advanced_brief": gen.advanced_brief,
                "status": gen.status,
                "requested_count": gen.requested_count,
                "returned_count": len(gen.names),
                "created_at": gen.created_at.isoformat(),
            }
        )
    return jsonify({"generations": result}), 200


@bp.get("/history/<generation_id>")
@login_required
def history_detail(generation_id):
    user = g.current_user
    gen = Generation.query.filter_by(id=generation_id, user_id=user.id).first()
    if not gen:
        return jsonify({"error": "Generation not found."}), 404
    names = GeneratedName.query.filter_by(generation_id=gen.id).order_by(GeneratedName.rank).all()
    return (
        jsonify(
            {
                "id": gen.id,
                "business_description": gen.business_description,
                "industry": gen.industry,
                "inspirations": gen.inspirations,
                "style_tags": gen.style_tags,
                "advanced_brief": gen.advanced_brief,
                "trademark_jurisdiction": infer_jurisdiction(gen.advanced_brief),
                "status": gen.status,
                "created_at": gen.created_at.isoformat(),
                "names": [n.to_dict() for n in names],
            }
        ),
        200,
    )
