"""Suggest daily macro nutrition goals from profile data.

Uses Mifflin-St Jeor BMR × sedentary-to-active multiplier, then splits
calories into protein / carbs / fat / fiber / sugar targets.

When the user has manually set goals in their profile those are returned
as-is; this function only fills in missing values from the algorithm.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict


class NutritionGoals(TypedDict):
    calorie_goal: float
    protein_g_goal: float
    carbs_g_goal: float
    fat_g_goal: float
    fiber_g_goal: float
    sugar_g_goal: float
    source: str  # "set" | "suggested" | "default"


_DEFAULT_ACTIVITY = 1.55  # moderately active


def _bmr(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if sex.startswith("m") else base - 161


def suggest_goals(
    weight_kg: float | None,
    height_cm: float | None,
    birthday: str | None,
    sex_at_birth: str | None,
    activity_factor: float = _DEFAULT_ACTIVITY,
) -> NutritionGoals:
    """Return algorithmically suggested goals; falls back to population defaults."""
    age: int | None = None
    if birthday:
        try:
            bd = date.fromisoformat(birthday)
            today = date.today()
            age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        except ValueError:
            pass

    if weight_kg and height_cm and age and sex_at_birth:
        tdee = _bmr(weight_kg, height_cm, age, sex_at_birth) * activity_factor
        protein_g = round(weight_kg * 1.6, 1)
        fat_g = round(tdee * 0.28 / 9, 1)
        carbs_g = round((tdee - protein_g * 4 - fat_g * 9) / 4, 1)
        fiber_g = 30.0 if sex_at_birth.startswith("m") else 25.0
        sugar_g = round(tdee * 0.08 / 4, 1)
        return NutritionGoals(
            calorie_goal=round(tdee),
            protein_g_goal=protein_g,
            carbs_g_goal=max(carbs_g, 50.0),
            fat_g_goal=fat_g,
            fiber_g_goal=fiber_g,
            sugar_g_goal=sugar_g,
            source="suggested",
        )

    # Population defaults when profile is incomplete
    return NutritionGoals(
        calorie_goal=2000.0,
        protein_g_goal=100.0,
        carbs_g_goal=250.0,
        fat_g_goal=65.0,
        fiber_g_goal=28.0,
        sugar_g_goal=50.0,
        source="default",
    )


def merge_with_profile(
    profile_goals: dict[str, float | None],
    suggested: NutritionGoals,
) -> NutritionGoals:
    """Overlay any user-set goals onto the suggested defaults.

    Fields explicitly set in the profile win; missing ones fall back to
    the algorithm output.
    """
    keys = ("calorie_goal", "protein_g_goal", "carbs_g_goal", "fat_g_goal", "fiber_g_goal", "sugar_g_goal")
    any_set = any(profile_goals.get(k) is not None for k in keys)
    result: dict = {}
    for k in keys:
        v = profile_goals.get(k)
        result[k] = v if v is not None else suggested[k]  # type: ignore[literal-required]
    result["source"] = "set" if any_set else suggested["source"]
    return NutritionGoals(**result)
