"""Food nutrition estimation via DeepSeek.

Uses a direct LLM call (no tool loop) to estimate macronutrients for a food
description + optional portion weight. Returns None on any failure so callers
can treat nutrition as optional enrichment that never blocks the primary action.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from lattice.integrations.deepseek import DeepSeekAuthMissing, DeepSeekUnavailable, chat_completion

logger = logging.getLogger(__name__)

_PROMPT = """\
You are a clinical nutritionist with access to USDA FoodData Central and European food databases.
Estimate the nutritional content of the food below for the stated portion.
Return ONLY a valid JSON object — no markdown, no explanation, no extra text.

Food: {description}
Portion: {portion_note}

Required JSON (all numbers are for the STATED portion, rounded to 1 decimal):
{{
  "calories": <number>,
  "protein_g": <number>,
  "carbs_g": <number>,
  "fat_g": <number>,
  "fiber_g": <number>,
  "sugar_g": <number>,
  "estimated_grams": <number>,
  "confidence": "high" | "medium" | "low",
  "notes": <string or null>
}}

confidence levels:
- "high"   → simple, well-defined food (e.g. "chicken breast 150g", "apple 100g")
- "medium" → mixed dish or approximate portion (e.g. "chicken salad 400g", "pasta bolognese")
- "low"    → vague, highly variable, or unknown portion size"""


@dataclass(slots=True)
class NutritionEstimate:
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sugar_g: float
    estimated_grams: float
    confidence: str  # high / medium / low
    notes: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


async def estimate_nutrition(
    description: str,
    grams: float | None = None,
) -> NutritionEstimate | None:
    """Estimate macronutrients for a food description.

    Returns None on any failure — API unavailable, key missing, or malformed
    response. Never raises; callers should treat None as "not available."
    """
    if not description or not description.strip():
        return None

    portion_note = (
        f"{grams:.0f}g" if grams else "typical serving (also estimate the weight in grams)"
    )
    prompt = _PROMPT.format(description=description.strip(), portion_note=portion_note)

    try:
        resp = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        return NutritionEstimate(
            calories=round(float(data.get("calories") or 0), 1),
            protein_g=round(float(data.get("protein_g") or 0), 1),
            carbs_g=round(float(data.get("carbs_g") or 0), 1),
            fat_g=round(float(data.get("fat_g") or 0), 1),
            fiber_g=round(float(data.get("fiber_g") or 0), 1),
            sugar_g=round(float(data.get("sugar_g") or 0), 1),
            estimated_grams=round(float(data.get("estimated_grams") or grams or 0), 1),
            confidence=str(data.get("confidence", "low")),
            notes=data.get("notes") or None,
        )
    except (DeepSeekAuthMissing, DeepSeekUnavailable) as exc:
        logger.debug("nutrition estimation skipped (deepseek unavailable): %s", exc)
        return None
    except Exception as exc:
        logger.warning("nutrition estimation failed for %r: %s", description, exc)
        return None


__all__ = ["NutritionEstimate", "estimate_nutrition"]
