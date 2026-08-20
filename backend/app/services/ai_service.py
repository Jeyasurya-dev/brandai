"""
AIService
---------
Wraps the LLM provider used for brand-name generation. Kept modular so the
underlying provider (Google Gemini today) can be swapped without touching the
rest of the pipeline (filtering, ranking, screening).

The service ALWAYS asks the model for structured JSON and validates the
response server-side. It never trusts free-form text parsing, and it never
fabricates results if the provider is unavailable — it raises AIServiceError
instead so the route layer can return a clear, honest error to the client.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from flask import current_app


class AIServiceError(Exception):
    pass


@dataclass
class NameCandidate:
    name: str
    meaning: str
    inspiration_used: str
    style_alignment: str
    brandability_score: float = 0.0


SYSTEM_PROMPT = """
You are an expert brand naming strategist and brand identity consultant.

Your primary objective is to create ORIGINAL brand names that are strongly
connected to the user's actual business, product, target audience, industry,
core value proposition, and requested inspirations.

IMPORTANT PRIORITY ORDER:

1. BUSINESS RELEVANCE
2. USER INSPIRATIONS
3. TARGET INDUSTRY
4. BRAND CONCEPT
5. REQUESTED STYLE
6. MEMORABILITY AND PHONETICS

Do NOT generate names based mainly on generic luxury, futuristic, spiritual,
premium, or abstract words.

The business description is the most important source of meaning.

Before generating names, internally identify:
- What the business actually does
- The main problem it solves
- The main product or service
- The target users/customers
- The most important concepts and keywords
- The emotional positioning of the brand
- The supplied inspirations and their meanings/symbolism
- The requested style

Every generated name must have a clear conceptual relationship to the
business.

For example:

If the business is an AI farming platform, names should relate to concepts
such as agriculture, crops, intelligence, growth, soil, farmers, nature,
precision, or smart farming.

If the business is an AI education platform, names should relate to learning,
knowledge, coaching, intelligence, progress, students, skills, or education.

If the business is a finance platform, names should relate to money, wealth,
finance, savings, budgeting, trust, growth, security, or financial intelligence.

If the business is a healthcare platform, names should relate to health,
wellness, care, diagnosis, recovery, life, or medical intelligence.

Do NOT simply select random words from Latin, Greek, Sanskrit, mythology,
philosophy, spirituality, or luxury vocabulary just because the requested
style sounds premium or futuristic.

INSPIRATION HANDLING:

INSPIRATION IS A CORE REQUIREMENT:

When the user provides one or more inspirations, you MUST actively use them
when creating the names.

Do NOT treat inspirations as optional suggestions.

For every generated candidate, internally identify:
1. Which business concept influenced the name.
2. Which user-provided inspiration influenced the name.
3. How the inspiration connects to the business.
4. How the requested style influences the final naming.

The inspiration does NOT have to appear literally in the final name.

Instead, extract and use:
- meaning
- symbolism
- mythology
- cultural associations
- attributes
- phonetics
- related concepts
- stories
- characteristics
- visual associations

IMPORTANT:
The inspiration must contribute something meaningful to the name.

For example:

If the user provides:
Business = dairy company
Inspiration = Krishna

Relevant concepts may include:
cows, pastoral life, nourishment, abundance, care, childhood,
flute, nature, devotion, joy, protection, prosperity.

The generated name should combine relevant dairy concepts with one or more
of these Krishna-related concepts.

If the user provides:
Business = technology company
Inspiration = Murugan

Relevant concepts may include:
courage, wisdom, leadership, victory, protection, precision,
strength, youth, Tamil heritage, intelligence.

The generated name should combine relevant technology concepts with
one or more of these Murugan-related concepts.

MULTIPLE INSPIRATIONS:

When multiple inspirations are provided, use ALL of them across the candidate
pool.

Do NOT use only the first inspiration.

For example:
Inspiration = Krishna, Murugan

The candidate pool should contain names influenced by:
- Krishna alone + business
- Murugan alone + business
- shared concepts between Krishna and Murugan + business
- creative combinations of their symbolic attributes + business

At least 70% of the final candidates must clearly use at least one
user-provided inspiration.

At least 30% should meaningfully incorporate two or more supplied inspirations
when multiple inspirations are provided.

INSPIRATION TRACEABILITY:

The "inspiration_used" field is mandatory and must explicitly state the
user-provided inspiration used.

Bad:
"inspired by mythology"

Good:
"Krishna — pastoral abundance and nourishment, adapted to the dairy brand."

Good:
"Murugan — strength and protection combined with the brand's focus on
trusted family nutrition."

Good:
"Krishna + Murugan — abundance, protection, and cultural heritage combined
with the dairy business."

Never claim an inspiration was used if it did not influence the name.
NAME CONSTRUCTION:

Use a balanced mixture of:
- meaningful invented words
- intelligent portmanteaus
- semantic blends
- meaningful abbreviations
- phonetic adaptations
- language-root inspired names
- metaphorical names
- conceptual names

Do not make every name a dictionary word.

Do not make every name an abstract invented word either.

At least 70% of the candidates must have an identifiable conceptual connection
to the business description.

The remaining candidates can be more abstract but must still fit the business
and requested brand positioning.

QUALITY RULES:

- Prefer short names.
- Prefer easy pronunciation.
- Prefer easy spelling.
- Prefer strong memorability.
- Avoid generic names such as AIHub, TechAI, SmartAI, FutureAI, NextGen,
  DigitalX, TechNova unless the concept genuinely requires them.
- Avoid obvious keyword stuffing.
- Avoid meaningless random syllables.
- Avoid direct copying of famous brands.
- Avoid names that are simply existing common words unless they provide a
  strong strategic brand meaning.
- Do not intentionally create a name that is confusingly similar to a famous
  existing company.

IMPORTANT:
The names should feel like they were strategically created specifically
for THIS business, not generated from a generic "premium technology company"
template.

ADVANCED BRIEF SIGNALS (when provided):

A user may optionally supply additional brief signals beyond the core
business description, inspirations, and style. These REFINE the naming
process within the SAME priority order above — they never override business
relevance or the supplied inspirations, and they never invent an inspiration
that wasn't given.

When present, use advanced signals like this:
- Target audience / target market: shape tone, cultural register, and
  vocabulary so the name resonates with that specific audience/market.
- Brand personality: shape the emotional voice of the name (e.g. playful
  vs. authoritative).
- Desired meaning / associations: treat as required conceptual anchors the
  name should evoke.
- Name length / name structure: treat as a soft constraint on candidates —
  prefer it, but do not sacrifice business relevance to force-fit it.
- Words to include: draw from these as raw material (roots, syllables,
  concepts) rather than pasting them in unchanged.
- Words to avoid / names the user dislikes: NEVER use these words, and
  never produce a name that closely echoes a disliked name.
- Names the user likes: use only as a directional style reference (tone,
  length, construction) — never copy or lightly reskin one of these names.
- Competitor / reference brands: use to differentiate — do not produce a
  name that could be confused with a listed competitor.
- Brand story / future expansion / five-year vision: use as extra context
  that can inform the "meaning" explanation, especially for how well a name
  will scale as the brand grows.
- Domain preference / trademark strategy: informational context only: they
  do not change naming style, but you may reflect them in "style_alignment"
  when directly relevant (e.g. noting a name reads as more availability
  friendly if a .com is required).

If NO advanced signals are supplied, proceed exactly as before, using only
the business description, inspirations, and style.

RESPONSE FORMAT:

Return ONLY a valid JSON array.

Each element must contain exactly these fields:

{
  "name": "string",
  "meaning": "1-2 sentences explaining the business connection and name origin",
  "inspiration_used": "string explaining which business concept, keyword,
  inspiration, symbolism, or naming technique influenced the name",
  "style_alignment": "string explaining how the name fits the requested style",
  "brandability_score": 0-100
}

Do not include markdown.
Do not include ```json.
Do not include explanations outside the JSON array.
"""


ADVANCED_FIELD_LABELS = {
    "naming_for": "What is being named",
    "target_audience": "Target audience",
    "target_market": "Target market",
    "naming_language": "Naming language / linguistic direction",
    "name_length": "Preferred name length",
    "name_structure": "Preferred name structure",
    "desired_meaning": "Desired meaning / associations",
    "brand_personality": "Brand personality",
    "competitors": "Competitor / reference brands (differentiate from these)",
    "names_liked": "Names the user likes (style reference only, do not copy)",
    "names_disliked": "Names the user dislikes (avoid this direction)",
    "words_to_include": "Words/roots to include or draw from",
    "words_to_avoid": "Words to avoid entirely",
    "brand_story": "Brand story / emotional direction",
    "future_expansion": "Future expansion plans",
    "five_year_vision": "Five-year vision",
    "domain_preference": "Domain preference",
    "trademark_strategy": "Trademark strategy",
}


def _format_advanced_brief(advanced):
    if not advanced:
        return "No advanced brief signals provided — rely on the business description, inspirations, and style alone."
    lines = []
    for key, label in ADVANCED_FIELD_LABELS.items():
        val = advanced.get(key)
        if not val:
            continue
        if isinstance(val, list):
            val = ", ".join(val)
        lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else "No advanced brief signals provided."


def _build_user_prompt(business_description, industry, inspirations, style_tags, count, advanced=None):
    inspiration_text = ", ".join(inspirations) if inspirations else "none specified — use the business description itself"
    style_text = ", ".join(style_tags) if style_tags else "no strict style constraint"
    advanced_text = _format_advanced_brief(advanced)
    return f"""
BUSINESS BRIEF
--------------
Business description:
{business_description}

Industry:
{industry or "not specified"}

Inspiration(s):
{inspiration_text}

Desired style:
{style_text}

ADVANCED BRIEF SIGNALS
-----------------------
{advanced_text}

TASK
----
Generate exactly {count} distinct brand name candidates.

The names MUST be primarily derived from the business itself.

First understand what the business does, who it serves, what problem it
solves, and what makes it valuable.

Then connect those business concepts with the supplied inspiration(s) and
desired style, refined by any advanced brief signals above.

For every candidate, the meaning must explain:
1. What business concept influenced the name.
2. What inspiration or symbolism influenced it, if applicable.
3. Why the resulting name fits this specific business.

Do not generate generic premium/futuristic names that could belong to any
technology company.

Do not generate names simply because they sound sophisticated.

The final candidates should make sense specifically for this business.
Return the candidates using the required JSON schema exactly.
"""


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    return text.strip()


BRIEF_FIELDS = [
    "industry",
    "target_market",
    "audience",
    "positioning",
    "personality",
    "naming_direction",
    "language",
    "expansion",
]

BRIEF_SYSTEM_PROMPT = """
You are a branding strategist helping a founder turn a short, casual
description of a business idea into a structured naming brief.

Given the business idea below, infer the following fields as best you
reasonably can from what was actually said. Do not invent specific facts
that weren't implied (e.g. don't invent a named competitor). If a field
truly cannot be reasonably inferred, use the string "Not specified".

Return ONLY a valid JSON object with exactly these fields:

{
  "industry": "string, e.g. Dairy / FMCG",
  "target_market": "string, e.g. Tamil Nadu",
  "audience": "string, e.g. Families",
  "positioning": "string, e.g. Premium + Trusted",
  "personality": "string, e.g. Traditional + Modern",
  "naming_direction": "string, e.g. Short + Memorable",
  "language": "string, e.g. Tamil / Sanskrit inspired",
  "expansion": "string, e.g. Multiple dairy products"
}

Do not include markdown, code fences, or any explanation outside the JSON
object.
"""


def _validate_brief(data: dict) -> dict:
    brief = {}
    for field in BRIEF_FIELDS:
        val = data.get(field)
        val = str(val).strip()[:300] if val else ""
        brief[field] = val or "Not specified"
    return brief


INTELLIGENCE_FIELDS = [
    "memorability",
    "pronunciation",
    "distinctiveness",
    "premium_feel",
    "global_usability",
    "domain_potential",
    "existing_brand_signals",
]

INTELLIGENCE_SYSTEM_PROMPT = """
You are a branding analyst scoring a single already-generated brand name
candidate on independent qualitative dimensions.

You are NOT re-generating the name and NOT screening trademarks or domains
— those come from separate, real data sources. Do not comment on legal
availability at all.

Score each of the following from 0-100 (higher = better on that dimension),
based purely on the linguistic/branding qualities of the name itself:

- memorability: how easy the name is to recall after hearing it once
- pronunciation: how easy the name is to say correctly on first read
- distinctiveness: how unlikely this name is to be confused with common
  generic words or other brands, based on its construction
- premium_feel: how much the name reads as premium/high-end vs. generic
- global_usability: how easily the name works across languages/markets
  without awkward meanings or pronunciation issues
- domain_potential: how likely a short, clean web domain is gettable for a
  name with this structure (not an actual domain check — that is separate)

Also provide:
- existing_brand_signals: a short (1-2 sentence) note on whether this name
  resembles any well-known existing brand name/pattern you're aware of, or
  "No obvious resemblance to a known brand" if none. This is a knowledge
  recall note, not a trademark search.
- rationale: a short (1-2 sentence) plain-language summary tying the scores
  together.

Return ONLY a valid JSON object:
{
  "memorability": 0-100,
  "pronunciation": 0-100,
  "distinctiveness": 0-100,
  "premium_feel": 0-100,
  "global_usability": 0-100,
  "domain_potential": 0-100,
  "existing_brand_signals": "string",
  "rationale": "string"
}

Do not include markdown, code fences, or explanation outside the JSON
object.
"""


def _validate_intelligence(data: dict) -> dict:
    result = {}
    for field in INTELLIGENCE_FIELDS:
        if field == "existing_brand_signals":
            continue
        val = data.get(field)
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = 50.0
        result[field] = max(0.0, min(100.0, val))
    signals = data.get("existing_brand_signals")
    result["existing_brand_signals"] = str(signals).strip()[:300] if signals else "Not assessed."
    rationale = data.get("rationale")
    result["rationale"] = str(rationale).strip()[:400] if rationale else ""
    return result


REFINEMENT_DIRECTIONS = [
    "More Premium",
    "More Modern",
    "More Traditional",
    "More Indian",
    "More Global",
    "Shorter",
    "More Playful",
    "More Technical",
    "More Unique",
]

REFINEMENT_SYSTEM_PROMPT = """
You are refining ONE already-generated brand name candidate in a specific
new direction, while keeping it genuinely suitable for the same business.

Rules you MUST follow:
- Preserve business relevance: every refined name must still make sense for
  the business described below — not a generic name that could belong to
  any company.
- Preserve genuine inspiration relevance: if inspiration(s) were supplied,
  refined names should still connect to them where that genuinely fits the
  requested direction. Do NOT invent an inspiration that wasn't supplied.
- Follow the requested refinement direction as the primary axis of change.
- Avoid generic startup filler names.
- Do NOT mechanically mutate the original name — no adding/swapping a
  handful of letters, no appended suffixes like "-ify"/"-io"/"-X". Every
  candidate must be a genuinely distinct naming concept, not a spelling
  variant of the original.
- Do NOT copy or lightly reskin the name of a famous existing brand.
- The 5 candidates must be genuinely distinct from each other too, not five
  near-copies of the same one idea.

Return ONLY a valid JSON array of exactly 5 objects:
[
  {
    "name": "string",
    "meaning": "string explaining the naming concept",
    "why_refined": "string explaining how this reflects the requested direction",
    "inspiration_used": "string, or 'None' if no inspiration genuinely applies",
    "brandability_score": 0-100
  }
]

Do not include markdown, code fences, or explanation outside the JSON array.
"""


def _build_refinement_prompt(
    business_description, industry, inspirations, style_tags, advanced,
    original_name, original_meaning, direction,
):
    inspiration_text = ", ".join(inspirations) if inspirations else "none specified — do not invent one"
    style_text = ", ".join(style_tags) if style_tags else "no strict style constraint"
    advanced_text = _format_advanced_brief(advanced)
    return f"""
{REFINEMENT_SYSTEM_PROMPT}

ORIGINAL BUSINESS BRIEF
------------------------
Business description:
{business_description}

Industry:
{industry or "not specified"}

Inspiration(s):
{inspiration_text}

Desired style:
{style_text}

ADVANCED BRIEF SIGNALS
-----------------------
{advanced_text}

NAME BEING REFINED
-------------------
Name: {original_name}
Original meaning/rationale: {original_meaning or "not provided"}

REQUESTED REFINEMENT DIRECTION
--------------------------------
{direction}

Generate exactly 5 refined candidates now, following every rule above.
Return ONLY the JSON array.
"""


def _validate_refinement_candidates(raw_list):
    """Never trust the Gemini response directly: check structure, required
    non-empty fields, and clamp the score. Incomplete candidates are
    dropped rather than passed through with missing data."""
    valid = []
    if not isinstance(raw_list, list):
        return valid
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        meaning = str(item.get("meaning") or "").strip()
        why_refined = str(item.get("why_refined") or "").strip()
        inspiration_used = str(item.get("inspiration_used") or "").strip()
        if not name or not meaning or not why_refined:
            continue
        try:
            score = float(item.get("brandability_score"))
        except (TypeError, ValueError):
            score = 50.0
        score = max(0.0, min(100.0, score))
        valid.append(
            {
                "name": name[:100],
                "meaning": meaning[:500],
                "why_refined": why_refined[:500],
                "inspiration_used": inspiration_used[:150] or "None",
                "brandability_score": score,
            }
        )
    return valid


TAGLINE_SYSTEM_PROMPT = """
You are writing short marketing taglines for ONE already-chosen brand name.

Rules you MUST follow:
- Every tagline must genuinely fit the business described below — not a
  generic tagline that could belong to any company.
- Keep each tagline short: aim for under 8 words, never more than 12.
- Do not repeat the brand name inside the tagline unless it reads naturally.
- Do not invent facts about the business that weren't stated (no specific
  numbers, awards, dates, or claims not implied by the description).
- Produce genuinely distinct taglines from each other — different angles
  (e.g. one on the core benefit, one on emotion, one on trust/heritage if
  relevant), not five reworded copies of the same line.
- Avoid generic startup-marketing filler ("Empowering tomorrow, today.").

Return ONLY a valid JSON array of exactly 5 strings:
["Tagline one", "Tagline two", "Tagline three", "Tagline four", "Tagline five"]

Do not include markdown, code fences, or explanation outside the JSON array.
"""


def _build_tagline_prompt(name, meaning, business_description, brand_story):
    return f"""
{TAGLINE_SYSTEM_PROMPT}

BRAND
-----
Name: {name}
Meaning/naming rationale: {meaning or "not provided"}
Business: {business_description or "not provided"}
Brand story (if the user wrote one): {brand_story or "not provided"}

Generate exactly 5 taglines now. Return ONLY the JSON array.
"""


def _validate_taglines(raw_list):
    if not isinstance(raw_list, list):
        return []
    out = []
    for item in raw_list:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().strip('"').strip()
        if cleaned:
            out.append(cleaned[:120])
    return out[:5]


def _extract_json_array(text: str):
    text = _strip_markdown_fences(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back: find the first [...] block.
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise AIServiceError("AI response was not valid JSON and no JSON array could be recovered.")
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise AIServiceError("AI response JSON was not a list of candidates.")
    return data


def _extract_json_object(text: str):
    text = _strip_markdown_fences(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise AIServiceError("AI response was not valid JSON and no JSON object could be recovered.")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise AIServiceError("AI response JSON was not an object.")
    return data


def _validate_candidates(raw_list) -> List[NameCandidate]:
    candidates = []
    required_fields = {"name", "meaning", "inspiration_used", "style_alignment", "brandability_score"}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        if not required_fields.issubset(item.keys()):
            continue
        name = str(item["name"]).strip()
        if not name or len(name) > 60:
            continue
        try:
            score = float(item["brandability_score"])
        except (TypeError, ValueError):
            score = 50.0
        score = max(0.0, min(100.0, score))
        candidates.append(
            NameCandidate(
                name=name,
                meaning=str(item["meaning"]).strip()[:1000],
                inspiration_used=str(item["inspiration_used"]).strip()[:255],
                style_alignment=str(item["style_alignment"]).strip()[:500],
                brandability_score=score,
            )
        )
    return candidates


class AIService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_app_config(cls):
        return cls(
            api_key=current_app.config.get("GEMINI_API_KEY"),
            model=current_app.config.get("AI_MODEL"),
        )

    def generate_candidate_pool(
        self,
        business_description: str,
        industry: Optional[str],
        inspirations: List[str],
        style_tags: List[str],
        pool_size: int = 60,
        advanced: Optional[dict] = None,
    ) -> List[NameCandidate]:
        """
        Generate a large internal candidate pool
        for filtering and ranking.
        """

        if not self.is_configured():
            raise AIServiceError(
                "AI name generation is not configured on this server. "
                "Set GEMINI_API_KEY in the backend environment."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise AIServiceError(
                f"Google GenAI SDK not installed: {e}"
            )

        user_prompt = _build_user_prompt(
            business_description,
            industry,
            inspirations,
            style_tags,
            pool_size,
            advanced,
        )

        full_prompt = f"""
{SYSTEM_PROMPT}

{user_prompt}

IMPORTANT:
Return ONLY a valid JSON array.
Do not include markdown formatting or code fences.
"""

        try:
            client = genai.Client(
                api_key=self.api_key
            )

            response = client.models.generate_content(
                model=self.model,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )

        except Exception as e:
            raise AIServiceError(
                f"Gemini provider request failed: {e}"
            )

        raw_text = response.text

        if not raw_text:
            raise AIServiceError(
                "Gemini returned an empty response."
            )

        raw_list = _extract_json_array(raw_text)

        candidates = _validate_candidates(raw_list)

        if not candidates:
            raise AIServiceError(
                "AI response did not contain any valid "
                "candidates after validation."
            )

        return candidates

    def build_brief(self, description: str) -> dict:
        """
        AI Brief Builder: turns a short, casual business description into a
        structured naming brief the user can review/edit before generating
        names. This does NOT generate names itself and does NOT replace the
        manual form — it's an optional helper that pre-fills it.
        """
        if not self.is_configured():
            raise AIServiceError(
                "AI Brief Builder is not configured on this server. "
                "Set GEMINI_API_KEY in the backend environment."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise AIServiceError(f"Google GenAI SDK not installed: {e}")

        prompt = f"""
{BRIEF_SYSTEM_PROMPT}

BUSINESS IDEA
-------------
{description}

Return ONLY the JSON object described above.
"""

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
        except Exception as e:
            raise AIServiceError(f"Gemini provider request failed: {e}")

        raw_text = response.text
        if not raw_text:
            raise AIServiceError("Gemini returned an empty response.")

        data = _extract_json_object(raw_text)
        return _validate_brief(data)

    def assess_brand_intelligence(self, name: str, meaning: str, business_description: str) -> dict:
        """
        Brand Intelligence: independent AI-derived heuristic scores for a
        single already-generated name (memorability, pronunciation,
        distinctiveness, premium feel, global usability, domain potential,
        existing-brand-signals recall). This NEVER touches trademark/domain
        screening — those come from TrademarkService/DomainService, which
        query real data sources. This method only produces a qualitative,
        clearly-labeled AI estimate; callers must present it as such and
        never merge it into real screening results as if it were verified
        data.
        """
        if not self.is_configured():
            raise AIServiceError(
                "Brand Intelligence is not configured on this server. "
                "Set GEMINI_API_KEY in the backend environment."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise AIServiceError(f"Google GenAI SDK not installed: {e}")

        prompt = f"""
{INTELLIGENCE_SYSTEM_PROMPT}

NAME TO ASSESS
---------------
Name: {name}
Meaning/rationale as generated: {meaning or "not provided"}
Business context: {business_description or "not provided"}

Return ONLY the JSON object described above.
"""

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
        except Exception as e:
            raise AIServiceError(f"Gemini provider request failed: {e}")

        raw_text = response.text
        if not raw_text:
            raise AIServiceError("Gemini returned an empty response.")

        data = _extract_json_object(raw_text)
        return _validate_intelligence(data)

    def refine_name(
        self,
        business_description: str,
        industry: Optional[str],
        inspirations: List[str],
        style_tags: List[str],
        advanced: Optional[dict],
        original_name: str,
        original_meaning: str,
        direction: str,
    ) -> List[dict]:
        """
        Name Refinement: generates 5 new naming concepts derived from one
        already-generated name, along a single requested direction (e.g.
        "More Modern"), while keeping the same original business context
        and inspiration(s) in scope. Reuses the same Gemini client as
        candidate generation, brief building, and brand intelligence — no
        duplicated provider configuration.
        """
        if not self.is_configured():
            raise AIServiceError(
                "Name refinement is not configured on this server. "
                "Set GEMINI_API_KEY in the backend environment."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise AIServiceError(f"Google GenAI SDK not installed: {e}")

        prompt = _build_refinement_prompt(
            business_description, industry, inspirations, style_tags, advanced,
            original_name, original_meaning, direction,
        )

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
        except Exception as e:
            raise AIServiceError(f"Gemini provider request failed: {e}")

        raw_text = response.text
        if not raw_text:
            raise AIServiceError("Gemini returned an empty response.")

        raw_list = _extract_json_array(raw_text)
        candidates = _validate_refinement_candidates(raw_list)

        if not candidates:
            raise AIServiceError(
                "AI response did not contain any valid refinement candidates after validation."
            )

        return candidates[:5]

    def generate_taglines(self, name: str, meaning: str, business_description: str, brand_story: str = None) -> List[str]:
        """AI Tagline Generator for the Brand Workspace: 5 short taglines
        for one already-chosen name. Reuses the same Gemini client as
        everything else — no duplicated provider logic."""
        if not self.is_configured():
            raise AIServiceError(
                "Tagline generation is not configured on this server. "
                "Set GEMINI_API_KEY in the backend environment."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise AIServiceError(f"Google GenAI SDK not installed: {e}")

        prompt = _build_tagline_prompt(name, meaning, business_description, brand_story)

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
        except Exception as e:
            raise AIServiceError(f"Gemini provider request failed: {e}")

        raw_text = response.text
        if not raw_text:
            raise AIServiceError("Gemini returned an empty response.")

        raw_list = _extract_json_array(raw_text)
        taglines = _validate_taglines(raw_list)

        if not taglines:
            raise AIServiceError("AI response did not contain any valid taglines after validation.")

        return taglines