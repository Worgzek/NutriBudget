
"""
app/meal_planning/optimizer.py
 
Tool thuần cho Meal Planning Agent - KHÔNG dùng LLM.
Bài toán "Diet Problem" kinh điển, giải bằng linear programming (PuLP).
 
Spec đã chốt:
- Solver tính cho 1 NGÀY, budget (tuần/tháng) quy đổi về budget/ngày trước khi đưa vào
- Giới hạn tối đa 400g/ngày cho mỗi loại thực phẩm (4 đơn vị x 100g)
- Calories trong khoảng ±10% target; protein/fat/carb là ràng buộc >= target
- Kết quả 1 ngày chia 3 bữa theo tỷ lệ cố định: sáng 25% / trưa 40% / tối 35%
- food_db truyền vào đã được lọc dị ứng từ trước (không lọc ở đây)
"""
 
import pulp
 
 
PERIOD_DAYS = {"weekly": 7, "monthly": 30}
MAX_UNITS_PER_FOOD = 4  # 4 x 100g = 400g/ngày/loại
CALORIE_TOLERANCE = 0.10  # +-10% quanh target
MIN_VEGETABLE_G = 150  # tối thiểu rau/ngày - tránh solver bỏ qua rau hoàn toàn vì chỉ tối ưu chi phí
 
MEAL_SPLIT = [
    ("Bữa sáng", 0.25),
    ("Bữa trưa", 0.40),
    ("Bữa tối", 0.35),
]
 
 
def _daily_budget(budget: dict) -> float:
    days = PERIOD_DAYS[budget["period"]]
    return budget["amount"] / days
 
 
def _build_and_solve(macro_targets: dict, daily_budget: float, food_db: list,
                      enforce_budget: bool = True):
    """Dựng và giải 1 lần bài toán LP. Trả về (status, x_values dict theo tên food)."""
    prob = pulp.LpProblem("diet_problem", pulp.LpMinimize)
 
    # Biến quyết định: số đơn vị (100g) của mỗi thực phẩm, 0 -> MAX_UNITS_PER_FOOD
    x = {
        food["name"]: pulp.LpVariable(f"x_{i}", lowBound=0, upBound=MAX_UNITS_PER_FOOD)
        for i, food in enumerate(food_db)
    }
 
    # Mục tiêu: tối thiểu hóa tổng chi phí
    prob += pulp.lpSum(food["price_per_unit"] * x[food["name"]] for food in food_db)
 
    # Ràng buộc macro - protein/fat/carb phải đạt ít nhất target
    prob += pulp.lpSum(food["protein"] * x[food["name"]] for food in food_db) >= macro_targets["protein_g"]
    prob += pulp.lpSum(food["fat"] * x[food["name"]] for food in food_db) >= macro_targets["fat_g"]
    prob += pulp.lpSum(food["carbs"] * x[food["name"]] for food in food_db) >= macro_targets["carb_g"]
 
    # Ràng buộc calories - trong khoảng +-10% target
    total_calories = pulp.lpSum(food["calories"] * x[food["name"]] for food in food_db)
    prob += total_calories <= macro_targets["calories"] * (1 + CALORIE_TOLERANCE)
    prob += total_calories >= macro_targets["calories"] * (1 - CALORIE_TOLERANCE)
 
    # Ràng buộc rau tối thiểu - solver chỉ tối ưu chi phí nên có xu hướng bỏ hẳn rau
    # (rau đóng góp ít protein/fat). Chỉ thêm ràng buộc nếu food_db có rau để chọn,
    # tránh vô nghiệm ngay lập tức nếu lỡ không còn rau nào (vd: bị lọc dị ứng hết).
    vegetable_foods = [food for food in food_db if food["category"] == "vegetable"]
    if vegetable_foods:
        total_vegetable_units = pulp.lpSum(x[food["name"]] for food in vegetable_foods)
        prob += total_vegetable_units >= MIN_VEGETABLE_G / 100
 
    # Ràng buộc ngân sách - có thể tắt khi cần thử "nếu không giới hạn budget thì tốn tối thiểu bao nhiêu"
    if enforce_budget:
        prob += pulp.lpSum(food["price_per_unit"] * x[food["name"]] for food in food_db) <= daily_budget
 
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
 
    status = pulp.LpStatus[prob.status]
    x_values = {name: var.value() for name, var in x.items()}
    total_cost = sum(
        food["price_per_unit"] * (x_values[food["name"]] or 0) for food in food_db
    )
    return status, x_values, total_cost
 
 
def _build_meals(x_values: dict, food_db: list) -> list:
    """Chia kết quả 1 ngày thành 3 bữa theo tỷ lệ cố định."""
    by_name = {food["name"]: food for food in food_db}
    meals = []
    for meal_name, ratio in MEAL_SPLIT:
        ingredients = []
        meal_calories = meal_protein = meal_fat = meal_carb = meal_cost = 0.0
        for name, units in x_values.items():
            if not units or units < 0.01:
                continue
            food = by_name[name]
            amount_g = units * 100 * ratio
            if amount_g < 1:  # bỏ qua lượng quá nhỏ, không đáng ghi vào thực đơn
                continue
            cost = food["price_per_unit"] * units * ratio
            ingredients.append({
                "name": name,
                "amount_g": round(amount_g, 1),
                "cost": round(cost, 0),
            })
            factor = (amount_g / 100)
            meal_calories += food["calories"] * factor
            meal_protein += food["protein"] * factor
            meal_fat += food["fat"] * factor
            meal_carb += food["carbs"] * factor
            meal_cost += cost
 
        meals.append({
            "meal_name": meal_name,
            "ingredients": ingredients,
            "macros": {
                "calories": round(meal_calories, 1),
                "protein_g": round(meal_protein, 1),
                "fat_g": round(meal_fat, 1),
                "carb_g": round(meal_carb, 1),
            },
            "meal_cost": round(meal_cost, 0),
        })
    return meals
 
 
def _try_solve_saver(macro_targets: dict, daily_budget: float, food_db: list):
    """Thử tìm giải pháp cứu vãn (Saver Plan) trong ngân sách hiện tại bằng cách
    tự động điều chỉnh nhẹ 15-25% chỉ tiêu dinh dưỡng nhưng vẫn giữ mức an toàn."""
    for scale in [0.85, 0.80, 0.75]:
        scaled_targets = {
            "calories": macro_targets["calories"] * scale,
            "protein_g": macro_targets["protein_g"] * scale,
            "fat_g": macro_targets["fat_g"] * scale,
            "carb_g": macro_targets["carb_g"] * scale,
        }
        status, x_val, cost = _build_and_solve(scaled_targets, daily_budget, food_db, enforce_budget=True)
        if status == "Optimal":
            return scale, x_val, cost
    return None, None, None


def optimize_meal_plan(macro_targets: dict, budget: dict, food_db: list) -> dict:
    """
    macro_targets: {"calories", "protein_g", "fat_g", "carb_g"} - target NGÀY (từ Agent 1)
    budget: {"amount", "period"} - "weekly" | "monthly"
    food_db: list các dict {"name","category","price_per_unit","calories","protein","carbs","fat",...}
             ĐÃ lọc dị ứng từ trước khi gọi hàm này.

    Trả về dict khớp MealPlanResponse (feasible, meals, total_cost_estimate, message, suggested_budget, scenarios).
    """
    daily_budget = _daily_budget(budget)
    days = PERIOD_DAYS[budget["period"]]
    p_unit = "tuần" if budget["period"] == "weekly" else "tháng"

    status, x_values, daily_cost = _build_and_solve(macro_targets, daily_budget, food_db, enforce_budget=True)

    if status == "Optimal":
        meals = _build_meals(x_values, food_db)
        return {
            "feasible": True,
            "meals": meals,
            "total_cost_estimate": round(daily_cost * days, 0),
            "message": None,
            "suggested_budget": None,
            "scenarios": None,
        }

    # Infeasible - thử lại KHÔNG giới hạn budget, để phân biệt 2 loại nguyên nhân:
    # (a) budget quá thấp so với macro target -> có nghiệm khi bỏ ràng buộc budget
    # (b) macro target không thể đạt được dù food_db/giới hạn 400g có rộng rãi thế nào
    status_relaxed, x_relaxed, min_cost = _build_and_solve(
        macro_targets, daily_budget, food_db, enforce_budget=False
    )

    if status_relaxed == "Optimal":
        suggested_total_budget = round(min_cost * days, 0)
        needed_more = max(suggested_total_budget - budget["amount"], 0)

        # Tự phản biện tìm Kịch bản Tiết kiệm trong ngân sách hiện tại
        scale_found, x_saver, saver_cost = _try_solve_saver(macro_targets, daily_budget, food_db)
        saver_meals = _build_meals(x_saver, food_db) if scale_found else []

        scenarios = {
            "has_remedy": True,
            "standard_scenario": {
                "title": "Kịch bản Chuẩn (Tăng nhẹ ngân sách)",
                "description": f"Bổ sung thêm khoảng {round(needed_more):,.0f}đ/{p_unit} để đạt 100% mục tiêu dinh dưỡng đề ra.",
                "suggested_budget": suggested_total_budget,
                "meals": _build_meals(x_relaxed, food_db),
            },
            "saver_scenario": {
                "title": "Kịch bản Tiết kiệm (Vừa khít ngân sách)",
                "description": f"Giữ nguyên ngân sách {round(budget['amount']):,.0f}đ/{p_unit} bằng cách tối ưu sang nguồn đạm bình dân (-{int((1-scale_found)*100)}% chỉ tiêu).",
                "meals": saver_meals,
                "total_cost": round(saver_cost * days, 0) if saver_cost else None,
            } if saver_meals else None,
        }

        return {
            "feasible": False,
            "meals": [],
            "total_cost_estimate": None,
            "message": (
                f"Với ngân sách hiện tại ({round(budget['amount']):,.0f}đ/{p_unit}), chưa đủ để đạt 100% mục tiêu dinh dưỡng ban đầu "
                f"(cần tối thiểu khoảng {round(suggested_total_budget):,.0f}đ/{p_unit}, thiếu khoảng {round(needed_more):,.0f}đ). "
                f"NutriBudget AI đã tự động đề xuất 2 kịch bản giải quyết: Kịch bản Tiết kiệm (vừa khít ngân sách hiện tại) "
                f"và Kịch bản Chuẩn (tăng ngân sách tối thiểu)."
            ),
            "suggested_budget": suggested_total_budget,
            "scenarios": scenarios,
        }

    # Vô nghiệm ngay cả khi không giới hạn budget - vấn đề nằm ở macro target hoặc food_db
    return {
        "feasible": False,
        "meals": [],
        "total_cost_estimate": None,
        "message": (
            "Không tìm được thực đơn đạt đủ chỉ tiêu dinh dưỡng với danh sách thực phẩm hiện có, "
            "dù ngân sách là bao nhiêu. Có thể do mục tiêu dinh dưỡng quá cao so với giới hạn khẩu phần "
            "mỗi loại thực phẩm, hoặc danh sách thực phẩm chưa đủ đa dạng."
        ),
        "suggested_budget": None,
        "scenarios": None,
    }