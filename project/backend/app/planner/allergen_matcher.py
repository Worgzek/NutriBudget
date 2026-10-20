"""Detect allergy-related notes only to request an explicit user selection.

The returned mentions are never used to filter food automatically. The user-selected
structured list is the sole source of truth for the meal planner.
"""

ALLERGEN_KEYWORDS = {
    "seafood": ["hải sản", "tôm", "cua", "mực", "cá", "seafood", "shrimp", "fish"],
    "dairy": ["sữa", "phô mai", "bơ sữa", "lactose", "dairy", "milk"],
    "peanut": ["đậu phộng", "lạc", "peanut"],
    "gluten": ["gluten", "lúa mì", "bột mì", "lúa mạch", "celiac"],
    "egg": ["trứng", "egg"],
    "soy": ["đậu nành", "đậu tương", "đậu phụ", "đậu hũ", "soy", "tofu"],
    "sesame": ["mè", "vừng", "tahini", "sesame"],
}

ALLERGY_CUES = (
    "dị ứng", "allergy", "allergic", "không dung nạp", "không ăn được",
    "không uống được", "không dùng được", "phản ứng với",
)


def extract_allergens_from_notes(notes) -> list[str]:
    """Return mentioned groups for clarification; never apply these as filters."""
    if not notes:
        return []
    text = notes.lower()
    return [
        group for group, words in ALLERGEN_KEYWORDS.items()
        if any(word in text for word in words)
    ]


def allergy_clarification_required(notes, selected_allergens) -> bool:
    """Require explicit selection when allergy-like wording is not fully mapped."""
    if not notes:
        return False
    text = notes.lower()
    if not any(cue in text for cue in ALLERGY_CUES):
        return False
    mentioned = set(extract_allergens_from_notes(text))
    selected = set(selected_allergens or [])
    return not mentioned or not mentioned.issubset(selected)
