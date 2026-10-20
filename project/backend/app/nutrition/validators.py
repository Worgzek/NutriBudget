from typing import Final


VALID_GENDERS: Final = {"male", "female"}

VALID_ACTIVITY_LEVELS: Final = {
    "sedentary",
    "light",
    "moderate",
    "heavy",
}

VALID_GOALS: Final = {
    "weight_loss",
    "maintain",
    "muscle_gain",
}

MIN_AGE: Final = 13
MAX_AGE: Final = 100

MIN_HEIGHT_CM: Final = 100.0
MAX_HEIGHT_CM: Final = 250.0

MIN_WEIGHT_KG: Final = 25.0
MAX_WEIGHT_KG: Final = 300.0


def validate_age(age: int) -> None:
    if not isinstance(age, int):
        raise ValueError("age phải là số nguyên.")

    if not MIN_AGE <= age <= MAX_AGE:
        raise ValueError(
            f"age phải nằm trong khoảng {MIN_AGE}-{MAX_AGE}."
        )


def validate_gender(gender: str) -> str:
    gender = gender.lower().strip()

    if gender not in VALID_GENDERS:
        raise ValueError(
            f"gender không hợp lệ: {gender}. "
            f"Giá trị hợp lệ: {', '.join(VALID_GENDERS)}."
        )

    return gender


def validate_activity_level(activity_level: str) -> str:
    activity_level = activity_level.lower().strip()

    if activity_level not in VALID_ACTIVITY_LEVELS:
        raise ValueError(
            f"activity_level không hợp lệ: {activity_level}. "
            f"Giá trị hợp lệ: {', '.join(VALID_ACTIVITY_LEVELS)}."
        )

    return activity_level


def validate_goal(goal: str) -> str:
    goal = goal.lower().strip()

    if goal not in VALID_GOALS:
        raise ValueError(
            f"goal không hợp lệ: {goal}. "
            f"Giá trị hợp lệ: {', '.join(VALID_GOALS)}."
        )

    return goal


def validate_height(height_cm: float) -> None:
    if height_cm <= 0:
        raise ValueError("height_cm phải lớn hơn 0.")

    if not MIN_HEIGHT_CM <= height_cm <= MAX_HEIGHT_CM:
        raise ValueError(
            f"height_cm phải nằm trong khoảng "
            f"{MIN_HEIGHT_CM}-{MAX_HEIGHT_CM}."
        )


def validate_weight(weight_kg: float) -> None:
    if weight_kg <= 0:
        raise ValueError("weight_kg phải lớn hơn 0.")

    if not MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG:
        raise ValueError(
            f"weight_kg phải nằm trong khoảng "
            f"{MIN_WEIGHT_KG}-{MAX_WEIGHT_KG}."
        )


def validate_profile(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str,
) -> dict:
    validate_weight(weight_kg)
    validate_height(height_cm)
    validate_age(age)

    gender = validate_gender(gender)
    activity_level = validate_activity_level(activity_level)
    goal = validate_goal(goal)

    return {
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "age": age,
        "gender": gender,
        "activity_level": activity_level,
        "goal": goal,
    }
