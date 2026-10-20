from typing import Optional, TypedDict
from .validators import validate_profile

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "heavy": 1.725,
}


GOAL_CALORIE_ADJUSTMENT = {
    "weight_loss": 0.80,
    "maintain": 1.0,
    "muscle_gain": 1.10,
}


GOAL_PROTEIN_PER_KG = {
    "weight_loss": 1.8,
    "maintain": 1.6,
    "muscle_gain": 2.0,
}


FAT_RATIO_OF_CALORIES = 0.25


LOW_CALORIE_THRESHOLD = {
    "male": 1500,
    "female": 1200,
}

MINOR_AGE_THRESHOLD = 18

class MacroResult(TypedDict):
    calories: float
    protein_g: float
    fat_g: float
    carb_g: float
    warnings: Optional[list[str]]


def calculate_bmr(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
) -> float:
    base = ((10 * weight_kg)+ (6.25 * height_cm)- (5 * age))
    if gender == "male":
        return base + 5
    return base - 161


def calculate_tdee(
    bmr: float,
    activity_level: str,
) -> float:
    multiplier = ACTIVITY_MULTIPLIERS[activity_level]
    return bmr * multiplier


def calculate_bmi(
    height_cm: float,
    weight_kg: float,
) -> float:
    height_m = height_cm / 100
    return weight_kg / (height_m ** 2)


def calculate_calorie_target(
    tdee: float,
    goal: str,
) -> float:
    adjustment = GOAL_CALORIE_ADJUSTMENT[goal]
    return tdee * adjustment


def calculate_macros(
    weight_kg: float,
    calories: float,
    goal: str,
    height_cm: Optional[float] = None,
) -> tuple[float, float, float]:
    effective_weight = weight_kg
    if height_cm and height_cm > 0:
        height_m = height_cm / 100
        bmi = weight_kg / (height_m ** 2)
        if bmi >= 25.0:
            # Đối với người thừa cân/béo phì (BMI >= 25), mô mỡ không có nhu cầu
            # tiêu thụ protein như khối cơ nạc. Theo chuẩn dinh dưỡng lâm sàng (ESPEN / ASPEN),
            # tính đạm theo Cân nặng Hiệu chỉnh (Adjusted Body Weight - ABW):
            # ABW = IBW + 0.25 * (weight_kg - IBW), với IBW tính theo BMI chuẩn 22.0.
            ideal_weight = 22.0 * (height_m ** 2)
            effective_weight = ideal_weight + 0.25 * (weight_kg - ideal_weight)

    # Protein
    protein_g = (
        effective_weight * GOAL_PROTEIN_PER_KG[goal]
    )

    protein_calories = protein_g * 4

    # Fat
    fat_calories = (
        calories * FAT_RATIO_OF_CALORIES
    )

    fat_g = fat_calories / 9

    # Carbohydrate
    carb_calories = max(
        calories
        - protein_calories
        - fat_calories,
        0,
    )

    carb_g = carb_calories / 4

    return (
        protein_g,
        fat_g,
        carb_g,
    )


def generate_warnings(
    age: int,
    calories: float,
    bmi: float,
    gender: str,
    goal: str,
) -> list[str]:
    warnings: list[str] = []
    threshold = LOW_CALORIE_THRESHOLD[gender]

    #emchua18
    if age < MINOR_AGE_THRESHOLD:
        warnings.append(
            f"Bạn dưới {MINOR_AGE_THRESHOLD} tuổi — các chỉ số này tính theo công thức "
            f"dành cho người trưởng thành, chưa tính đến nhu cầu phát triển thể chất ở "
            f"tuổi vị thành niên. Nên tham khảo ý kiến phụ huynh hoặc bác sĩ/chuyên gia "
            f"dinh dưỡng trước khi áp dụng, đặc biệt nếu mục tiêu là giảm cân hoặc tăng cân."
        )

    #clories thap hon tieu chuan
    if calories < threshold:
        warnings.append(
            f"Lượng calo ước tính ({round(calories)} kcal) "
            f"thấp hơn ngưỡng tiêu chuẩn ({threshold} kcal). "
            "Nên xem xét lại mục tiêu dinh dưỡng hoặc "
            "tham khảo chuyên gia."
        )

    # gay
    if bmi < 18.5:
        warnings.append(
            f"BMI ước tính ({bmi:.1f}) dưới 18.5. "
            "Nên cân nhắc mục tiêu dinh dưỡng và "
            "tham khảo chuyên gia nếu cần."
        )

    # bel
    elif bmi >= 30:
        warnings.append(
            f"BMI ước tính ({bmi:.1f}) từ 30 trở lên. "
            "Nên cân nhắc tham khảo chuyên gia trước "
            "khi thực hiện thay đổi lớn về chế độ ăn."
        )
    return warnings


def calculate_nutrition(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str,
) -> MacroResult:
    """
    Main entry point of the Nutrition Engine.

    Flow:
        Validate input
            ↓
        BMR
            ↓
        TDEE
            ↓
        Calorie target
            ↓
        Macro calculation
            ↓
        Warnings
            ↓
        MacroResult
    """

    # 1. Validate input
    profile = validate_profile(
        weight_kg=weight_kg,
        height_cm=height_cm,
        age=age,
        gender=gender,
        activity_level=activity_level,
        goal=goal,
    )

    weight_kg = profile["weight_kg"]
    height_cm = profile["height_cm"]
    age = profile["age"]
    gender = profile["gender"]
    activity_level = profile["activity_level"]
    goal = profile["goal"]

    # 2. Calculate BMR
    bmr = calculate_bmr(
        weight_kg=weight_kg,
        height_cm=height_cm,
        age=age,
        gender=gender,
    )

    # 3. Calculate TDEE
    tdee = calculate_tdee(
        bmr=bmr,
        activity_level=activity_level,
    )

    # 4. Calculate calories
    calories = calculate_calorie_target(
        tdee=tdee,
        goal=goal,
    )

    # 5. Calculate macros
    protein_g, fat_g, carb_g = calculate_macros(
        weight_kg=weight_kg,
        calories=calories,
        goal=goal,
        height_cm=height_cm,
    )

    # 6. Calculate BMI
    bmi = calculate_bmi(
        height_cm=height_cm,
        weight_kg=weight_kg,
    )

    # 7. Generate warnings
    warnings = generate_warnings(
        age=age,
        calories=calories,
        bmi=bmi,
        gender=gender,
        goal=goal,
    )

    # 8. Return result
    return {
        "calories": round(calories, 1),
        "protein_g": round(protein_g, 1),
        "fat_g": round(fat_g, 1),
        "carb_g": round(carb_g, 1),
        "warnings": warnings if warnings else None,
    }