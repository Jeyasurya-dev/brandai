"""
LogoGenerationService
----------------------
Independent image-generation service for brand logos — separate from
AIService (which handles text/JSON generation: naming, briefs, brand
intelligence, refinement). This keeps the two concerns cleanly split while
still reusing the SAME GEMINI_API_KEY: Google's Gemini Developer API serves
both the text models AIService uses and the Imagen image models this
service uses, through the same google-genai client. No second provider and
no second API key are introduced.

Uses the real, documented google-genai SDK method
`client.models.generate_images(model=..., prompt=..., config=...)` — see
https://ai.google.dev/gemini-api/docs/imagen. Nothing here is a fabricated
endpoint.

Never fabricates an image: if GEMINI_API_KEY is missing, the Imagen request
fails, or the provider returns nothing (e.g. safety-filtered), this raises
a clear LogoGenerationError instead of returning a placeholder image.
"""

import base64
from dataclasses import dataclass
from typing import List, Optional
from flask import current_app


class LogoGenerationError(Exception):
    pass


LOGO_TYPES = ["Wordmark", "Lettermark", "Symbol", "Abstract", "Mascot", "Combination"]

LOGO_TYPE_GUIDANCE = {
    "Wordmark": "a clean typographic wordmark logo that spells out the exact brand name in a custom-styled typeface",
    "Lettermark": "a lettermark logo using only the brand's initial letter(s), monogram-style",
    "Symbol": "an abstract or iconic symbol/pictorial mark with NO text at all",
    "Abstract": "an abstract geometric mark with NO text at all",
    "Mascot": "a simple, friendly mascot/character-style logo mark with NO surrounding text",
    "Combination": "a combination mark: a small icon paired with the brand name spelled out as clean typography",
}


@dataclass
class LogoResult:
    images_base64: List[str]  # PNG bytes, base64-encoded, ready for a data: URI
    prompt_used: str


class LogoGenerationService:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_app_config(cls):
        return cls(
            api_key=current_app.config.get("GEMINI_API_KEY", ""),
            model=current_app.config.get("IMAGE_MODEL", "imagen-4.0-generate-001"),
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_logos(
        self,
        brand_name: str,
        logo_type: str,
        style: Optional[str] = None,
        color_preference: Optional[str] = None,
        brand_description: Optional[str] = None,
        inspiration: Optional[str] = None,
        brand_personality: Optional[List[str]] = None,
        count: int = 3,
    ) -> LogoResult:
        if not self.is_configured():
            raise LogoGenerationError(
                "Logo generation is not configured on this server. "
                "Set GEMINI_API_KEY in the backend environment."
            )
        if logo_type not in LOGO_TYPES:
            raise LogoGenerationError(f"logo_type must be one of: {', '.join(LOGO_TYPES)}")

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LogoGenerationError(f"Google GenAI SDK not installed: {e}")

        prompt = self._build_prompt(
            brand_name, logo_type, style, color_preference, brand_description, inspiration, brand_personality
        )

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_images(
                model=self.model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=count,
                    output_mime_type="image/png",
                ),
            )
        except Exception as e:
            raise LogoGenerationError(f"Image provider request failed: {e}")

        images = getattr(response, "generated_images", None) or []
        if not images:
            raise LogoGenerationError(
                "The image provider returned no images for this request "
                "(it may have been filtered). Try adjusting the brand name or style."
            )

        encoded = []
        for img in images:
            try:
                raw_bytes = img.image.image_bytes
                encoded.append(base64.b64encode(raw_bytes).decode("ascii"))
            except Exception:
                continue

        if not encoded:
            raise LogoGenerationError("The image provider's response could not be decoded.")

        return LogoResult(images_base64=encoded, prompt_used=prompt)

    def _build_prompt(
        self, brand_name, logo_type, style, color_preference, brand_description, inspiration, brand_personality
    ):
        type_guidance = LOGO_TYPE_GUIDANCE.get(logo_type, "a clean professional logo")
        parts = [
            f'Design {type_guidance} for a brand called "{brand_name}".',
            "Professional branding style, flat vector-style illustration, centered composition, "
            "plain white background, no mockups, no photographs, no watermarks, no extra text "
            "beyond what is specified below.",
        ]
        if brand_description:
            parts.append(f"The business: {brand_description}.")
        if style:
            parts.append(f"Visual style: {style}.")
        if color_preference:
            parts.append(f"Color preference: {color_preference}.")
        if inspiration:
            parts.append(f"Symbolic inspiration to draw from subtly (not literally): {inspiration}.")
        if brand_personality:
            parts.append(f"Brand personality to convey: {', '.join(brand_personality)}.")
        if logo_type in ("Symbol", "Abstract", "Mascot"):
            parts.append("Do not include any text or letters in the image.")
        else:
            parts.append(f'If any text appears, it must read exactly "{brand_name}" with no misspellings.')
        return " ".join(parts)
