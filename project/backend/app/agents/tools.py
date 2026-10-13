"""
app/agents/tools.py

Tool cho ADK agent - bọc quanh các hàm thuần đã có (calculate_nutrition,
optimize_meal_plan, get_food_db), KHÔNG sửa logic bên trong chúng.

Nguyên tắc: tool ghi kết quả SỐ LIỆU vào session.state (qua ToolContext).
LLM chỉ đọc lại để diễn giải thành câu, không tự tính toán hay tự bịa số.
"""

from typing import Literal

from google.adk.tools.tool_context import ToolContext

from app.nutrition.calculator import calculate_nutrition
from app.planner.optimizer import optimize_meal_plan
from app.planner.query import get_food_db
from app.agents.chef import enhance_meals_with_chef


Gender = Literal["male", "female"]
ActivityLevel = Literal["sedentary", "light", "moderate", "heavy"]
Goal = Literal["weight_loss", "maintain", "muscle_gain"]
BudgetPeriod = Literal["weekly", "monthly"]
# Danh mục dị ứng cố định - dùng Literal để schema gửi cho LLM là enum,
# LLM không thể tự bịa thêm nhóm dị ứng ngoài 5 nhóm này.
Allergen = Literal["seafood", "dairy", "peanut", "gluten", "egg"]


def run_nutrition_calculation(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: Gender,
    activity_level: ActivityLevel,
    goal: Goal,
    tool_context: ToolContext,
) -> dict:
    """Tính BMR, TDEE, chỉ tiêu macro (calories/protein/fat/carb) và cảnh báo an toàn
    (nếu có) từ thông tin cơ thể và mục tiêu của người dùng.

    Luôn gọi tool này khi đã có đủ 6 thông tin: weight_kg, height_cm, age, gender,
    activity_level, goal. Không tự suy luận hay ước lượng số liệu - tool tính chính xác.

    Args:
        weight_kg: Cân nặng (kg).
        height_cm: Chiều cao (cm).
        age: Tuổi.
        gender: "male" hoặc "female".
        activity_level: "sedentary" | "light" | "moderate" | "heavy".
        goal: "weight_loss" | "maintain" | "muscle_gain".

    Returns:
        dict gồm calories, protein_g, fat_g, carb_g, warnings (list hoặc None).
    """
    result = calculate_nutrition(
        weight_kg=weight_kg,
        height_cm=height_cm,
        age=age,
        gender=gender,
        activity_level=activity_level,
        goal=goal,
    )
    # Ghi lại đúng tham số tool đã nhận - route đối chiếu với request gốc để phát hiện
    # trường hợp LLM chép sai số từ tin nhắn sang tham số tool.
    tool_context.state["nutrition_inputs"] = {
        "weight_kg": weight_kg, "height_cm": height_cm, "age": age,
        "gender": gender, "activity_level": activity_level, "goal": goal,
    }
    # Ghi vào session - bước /meal-plan sau này đọc lại, không cần client gửi lại
    tool_context.state["macro_targets"] = {
        "calories": result["calories"],
        "protein_g": result["protein_g"],
        "fat_g": result["fat_g"],
        "carb_g": result["carb_g"],
    }
    tool_context.state["warnings"] = result["warnings"]
    return result


def generate_meal_plan(
    budget_amount: float,
    budget_period: BudgetPeriod,
    allergens: list[Allergen],
    tool_context: ToolContext,
) -> dict:
    """Tạo thực đơn tối ưu chi phí, đạt đủ chỉ tiêu dinh dưỡng đã tính trước đó
    (lấy từ session, KHÔNG cần truyền lại), trong giới hạn ngân sách.

    Chỉ gọi tool này sau khi đã xác định xong allergens từ ghi chú người dùng.

    Args:
        budget_amount: Số tiền ngân sách.
        budget_period: "weekly" hoặc "monthly".
        allergens: Danh sách nhóm dị ứng người dùng thực sự đề cập trong ghi chú.
            CHỈ dùng giá trị trong: "seafood", "dairy", "peanut", "gluten", "egg".
            Truyền list rỗng [] nếu không có dị ứng nào được đề cập.

    Returns:
        dict gồm feasible, meals, total_cost_estimate, message, suggested_budget.
    """
    macro_targets = tool_context.state.get("macro_targets")
    if macro_targets is None:
        return {
            "error": "Chưa có macro_targets trong session. Cần tính macro "
                     "(gọi run_nutrition_calculation) trước khi tạo thực đơn."
        }

    food_db = get_food_db(exclude_allergens=allergens)
    if not food_db:
        return {"error": "Không còn thực phẩm nào phù hợp sau khi loại trừ dị ứng."}

    result = optimize_meal_plan(
        macro_targets=macro_targets,
        budget={"amount": budget_amount, "period": budget_period},
        food_db=food_db,
    )

    # Nếu tìm được thực đơn khả thi, Chef Agent tự động sáng tạo tên món và mẹo nấu 15p
    if result.get("feasible") and result.get("meals"):
        enhanced_meals, advice = enhance_meals_with_chef(result["meals"])
        result["meals"] = enhanced_meals
        if advice:
            result["ai_advice"] = advice

    # Nếu có kịch bản cứu vãn (Saver scenario), Chef Agent cũng tạo món cho kịch bản đó
    scenarios = result.get("scenarios")
    if scenarios and scenarios.get("saver_scenario"):
        saver_meals = scenarios["saver_scenario"].get("meals")
        if saver_meals:
            enh_saver, _ = enhance_meals_with_chef(saver_meals)
            scenarios["saver_scenario"]["meals"] = enh_saver

    # Ghi lại ngân sách tool đã dùng để route đối chiếu với request gốc, đồng thời
    # phân biệt kết quả của lượt này với kết quả cũ còn sót trong session.
    tool_context.state["meal_plan_budget"] = {
        "amount": budget_amount, "period": budget_period,
    }
    tool_context.state["meal_plan_result"] = result
    return result