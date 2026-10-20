"""
app/agents/tools.py

Tool cho ADK agent - bọc quanh các hàm thuần đã có (calculate_nutrition,
optimize_meal_plan, get_food_db), KHÔNG sửa logic bên trong chúng.

Nguyên tắc: tool ghi kết quả SỐ LIỆU vào session.state (qua ToolContext).
LLM chỉ đọc lại để diễn giải thành câu, không tự tính toán hay tự bịa số.
"""

from typing import Literal, Optional, List

from google.adk.tools.tool_context import ToolContext

from app.nutrition.calculator import calculate_nutrition
from app.planner.optimizer import optimize_meal_plan
from app.planner.query import get_food_db
from app.agents.chef import enhance_meals_with_chef


Gender = Literal["male", "female"]
ActivityLevel = Literal["sedentary", "light", "moderate", "heavy"]
Goal = Literal["weight_loss", "maintain", "muscle_gain"]
BudgetPeriod = Literal["weekly", "monthly"]
# Danh mục dị ứng cố định - đồng bộ với schema API, dữ liệu và giao diện.
Allergen = Literal["seafood", "dairy", "peanut", "gluten", "egg", "soy", "sesame"]


def _record_step(tool_context: ToolContext, actor: str, action: str, status: str, summary: str):
    trace = tool_context.state.setdefault("agent_trace", [])
    trace.append({
        "actor": actor,
        "action": action,
        "status": status,
        "summary": summary,
    })


def run_nutrition_calculation(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: Gender,
    activity_level: ActivityLevel,
    goal: Goal,
    tool_context: ToolContext,
) -> dict:
    """Tính BMR, TDEE, chỉ tiêu macro (calories/protein/fat/carb).

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
    _record_step(
        tool_context, "Nutrition Engine", "calculate_nutrition", "completed",
        "Đã tính mục tiêu dinh dưỡng bằng công thức xác định.",
    )
    return result


def generate_meal_plan(
    budget_amount: float,
    budget_period: BudgetPeriod,
    allergens: list[Allergen],
    tool_context: ToolContext,
    max_price_per_unit: Optional[float] = None,
    exclude_foods: Optional[List[str]] = None,
    reflection_note: Optional[str] = None,
) -> dict:
    """Tạo thực đơn tối ưu chi phí, đạt đủ chỉ tiêu dinh dưỡng đã tính trước đó
    (lấy từ session, KHÔNG cần truyền lại), trong giới hạn ngân sách.

    Hỗ trợ vòng lặp Tự phản biện & Tự sửa sai (Self-Reflection Loop):
    - Khi ngân sách eo hẹp (lượt trước infeasible): truyền max_price_per_unit (ví dụ: 18000 hoặc 20000)
      để tự động loại trừ nguyên liệu đắt đỏ, dồn ngân sách vào các nguồn đạm kinh tế.
    - Khi phát hiện món ăn bị lặp lại đơn điệu giữa các bữa: truyền exclude_foods (ví dụ: ["Trứng gà"])
      để yêu cầu solver thay thế món đạm khác cho hài hòa.
    - reflection_note: ghi lại lập luận phản biện của Agent để hiển thị trên vết thực thi (trace).

    Args:
        budget_amount: Số tiền ngân sách.
        budget_period: "weekly" hoặc "monthly".
        allergens: Danh sách nhóm dị ứng người dùng đã chọn rõ ràng.
        tool_context: Ngữ cảnh phiên làm việc ADK.
        max_price_per_unit: Trần giá tối đa của mỗi đơn vị (100g) nguyên liệu để tự điều chỉnh khi thiếu kinh phí.
        exclude_foods: Danh sách tên món ăn cụ thể Agent muốn loại trừ sau khi tự phản biện tính hài hòa.
        reflection_note: Lập luận tự phản biện và lý do điều chỉnh của Agent.

    Returns:
        dict gồm feasible, meals, total_cost_estimate, message, suggested_budget, scenarios, agent_reflection.
    """
    if reflection_note:
        _record_step(
            tool_context, "Meal Planning Agent", "self_reflection", "completed",
            reflection_note,
        )

    macro_targets = tool_context.state.get("macro_targets")
    if macro_targets is None:
        return {
            "error": "Chưa có macro_targets trong session. Cần tính macro "
                     "(gọi run_nutrition_calculation) trước khi tạo thực đơn."
        }

    requested_allergens = tool_context.state.get("meal_plan_requested_allergens")
    selected_allergens = sorted(set(
        requested_allergens if isinstance(requested_allergens, list) else (allergens or [])
    ))
    rotation_exclusions = sorted(set(tool_context.state.get("meal_plan_rotation_exclusions") or []))
    tool_context.state["meal_plan_filters"] = {
        "allergens": selected_allergens,
        "rotation_exclusions": rotation_exclusions,
    }
    food_db = get_food_db(exclude_allergens=selected_allergens)
    _record_step(
        tool_context, "Meal Planning Agent", "filter_foods", "completed",
        f"Đã lọc danh mục theo {len(selected_allergens)} nhóm loại trừ; còn {len(food_db)} mục.",
    )
    if rotation_exclusions:
        food_db = [food for food in food_db if food["name"] not in rotation_exclusions]
        _record_step(
            tool_context, "Meal Planning Agent", "rotate_menu", "completed",
            f"Đã tạm loại {len(rotation_exclusions)} nguyên liệu từ thực đơn trước để tìm lựa chọn khác.",
        )

    # 1. Cơ chế tự sửa sai 1: Giới hạn trần giá nguyên liệu khi ngân sách thấp
    if max_price_per_unit is not None and max_price_per_unit > 0:
        filtered_by_price = [f for f in food_db if f["price_per_unit"] <= max_price_per_unit]
        # Đảm bảo vẫn đủ nhóm đạm và tinh bột để bài toán khả thi
        if any(f["category"] == "protein" for f in filtered_by_price) and any(f["category"] == "carb" for f in filtered_by_price):
            food_db = filtered_by_price
            _record_step(
                tool_context, "Meal Planning Agent", "filter_price_ceiling", "completed",
                f"Đã tự động đặt trần giá nguyên liệu <= {max_price_per_unit:,.0f}đ/100g để tối ưu cho ngân sách thấp.",
            )

    # 2. Cơ chế tự sửa sai 2: Loại trừ món lặp hoặc đơn điệu để tăng tính hài hòa
    if exclude_foods:
        cleaned_excludes = [x.strip() for x in exclude_foods if x.strip()]
        if cleaned_excludes:
            filtered_by_harmony = [f for f in food_db if f["name"] not in cleaned_excludes]
            if any(f["category"] == "protein" for f in filtered_by_harmony) and any(f["category"] == "carb" for f in filtered_by_harmony):
                food_db = filtered_by_harmony
                _record_step(
                    tool_context, "Meal Planning Agent", "refine_harmony", "completed",
                    f"Đã tự động loại trừ {', '.join(cleaned_excludes)} để chống lặp món và tăng tính hài hòa.",
                )

    if not food_db:
        result = {
            "feasible": False,
            "meals": [],
            "total_cost_estimate": None,
            "message": "Không còn thực phẩm phù hợp với các nhóm đã chọn. Hãy sửa nhóm loại trừ hoặc sở thích.",
            "suggested_budget": None,
            "scenarios": None,
        }
        tool_context.state["meal_plan_budget"] = {"amount": budget_amount, "period": budget_period}
        tool_context.state["meal_plan_result"] = result
        return result

    result = optimize_meal_plan(
        macro_targets=macro_targets,
        budget={"amount": budget_amount, "period": budget_period},
        food_db=food_db,
    )
    _record_step(
        tool_context, "Meal Planner", "optimize_meal_plan",
        "feasible" if result.get("feasible") else "needs_user_choice",
        "Đã tìm phương án trong ngân sách." if result.get("feasible")
        else "Không có phương án trong ngân sách; giữ nguyên mục tiêu và tính mức tối thiểu.",
    )

    if reflection_note:
        result["agent_reflection"] = reflection_note

    # Nếu tìm được thực đơn khả thi, Chef Agent tự động sáng tạo tên món và mẹo nấu 15p
    if result.get("feasible") and result.get("meals"):
        enhanced_meals, advice, chef_status = enhance_meals_with_chef(result["meals"])
        result["meals"] = enhanced_meals
        if advice:
            result["ai_advice"] = advice
        _record_step(
            tool_context, "Chef", "suggest_cooking", chef_status,
            "Đã tạo gợi ý chế biến." if chef_status == "completed"
            else "Tạm dùng nguyên liệu từ solver; phần gợi ý món có thể thử lại sau.",
        )

    # Ghi lại ngân sách tool đã dùng để route đối chiếu với request gốc, đồng thời
    # phân biệt kết quả của lượt này với kết quả cũ còn sót trong session.
    tool_context.state["meal_plan_budget"] = {
        "amount": budget_amount, "period": budget_period,
    }
    tool_context.state["meal_plan_result"] = result
    return result
