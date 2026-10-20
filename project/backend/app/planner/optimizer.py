
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
CALORIE_TOLERANCE = 0.10      # +-10% quanh target cả ngày
MIN_VEGETABLE_G = 150         # tối thiểu rau/ngày (chỉ tính rau "thật", xem _counts_as_vegetable)

MEAL_SPLIT = [
    ("Bữa sáng", 0.25),
    ("Bữa trưa", 0.40),
    ("Bữa tối", 0.35),
]
MEAL_CAL_TOLERANCE = 0.20     # mỗi bữa lệch +-20% so với phần calo được chia

# --- Ánh xạ meal_types trong DB -> tên bữa ---
TAG_TO_MEALS = {
    "breakfast": ["Bữa sáng"],
    "lunch": ["Bữa trưa"],
    "dinner": ["Bữa tối"],
    "snack": ["Bữa trưa", "Bữa tối"], 
}

# --- Loại khỏi bài toán (gia vị, đường, đồ khô...) ---
EXCLUDED_CATEGORIES = {"other"}
EXCLUDED_NAMES = {"Xì dầu"}

# --- Khẩu phần thực tế (1 unit = 100g/100ml, tính cho CẢ NGÀY) ---
DEFAULT_MAX_UNITS = 2.5
CATEGORY_MAX_UNITS = {
    "protein": 2.5, "carb": 4.0, "vegetable": 2.0,
    "fruit": 2.0, "dairy": 2.5, "fat": 0.4,
}
NAME_MAX_UNITS = {   # ghi đè theo tên; hoặc thêm cột max_units vào DB (ưu tiên hơn)
    "Tỏi ta": 0.1, "Gừng": 0.1, "Hành lá (hành hoa)": 0.3,
    "Rau thơm": 0.3, "Hành tây": 0.5, "Lạc hạt, khô": 0.3, "Vừng": 0.2,
}
CATEGORY_GROUP_MAX_UNITS = {
    "protein": 5.5, "fat": 0.6, "vegetable": 4.5,
    "dairy": 3.0, "carb": 5.0,
}
CATEGORY_GROUP_MIN_UNITS = {"carb": 1.5}                  # tối thiểu 150g tinh bột nền/ngày
MAX_VEG_UNITS_PER_MEAL = 2.0
MAX_PROTEIN_UNITS_PER_MEAL = 2.5
MAX_PROTEIN_ITEMS_PER_MEAL = 2     # tối đa 2 loại đạm/bữa

# --- Đa dạng ---
MIN_UNITS_IF_USED = 0.3       # đã dùng món nào trong 1 bữa thì >= 30g
MIN_DISTINCT_TOTAL = 6        # tối thiểu số món khác nhau/ngày
CATEGORY_MIN_DISTINCT = {"protein": 2, "vegetable": 2}    # số món khác nhau/ngày theo nhóm
MAX_MEALS_PER_FOOD = {"protein": 2}                       # 1 món đạm không xuất hiện cả 3 bữa
MACRO_UPPER_RATIO = 1.4       # protein/fat/carb không vượt quá 140% target


# Mỗi bữa phải có: (các category được tính, số món tối thiểu)
MEAL_REQUIRED = {
    "Bữa sáng": [(["carb"], 1), (["protein", "dairy"], 1)],
    "Bữa trưa": [(["carb"], 1), (["protein"], 1), (["vegetable"], 1)],
    "Bữa tối": [(["carb"], 1), (["protein"], 1), (["vegetable"], 1)],
}

# --- Dùng ngân sách ---
BUDGET_UTILIZATION = 0.85
MAX_SPEND_OVER_MIN = 1.6


def _daily_budget(budget: dict) -> float:
    days = PERIOD_DAYS[budget["period"]]
    return budget["amount"] / days


def _usable_foods(food_db: list) -> list:
    return [
        f for f in food_db
        if f["category"] not in EXCLUDED_CATEGORIES and f["name"] not in EXCLUDED_NAMES
    ]


def _max_units(food: dict) -> float:
    if food.get("max_units") is not None:
        return float(food["max_units"])
    if food["name"] in NAME_MAX_UNITS:
        return NAME_MAX_UNITS[food["name"]]
    return CATEGORY_MAX_UNITS.get(food["category"], DEFAULT_MAX_UNITS)


def _allowed_meals(food: dict) -> list:
    """Các bữa món này được phép xuất hiện, theo meal_types. Không có/không map được = mọi bữa."""
    meals = set()
    for tag in food.get("meal_types") or []:
        meals.update(TAG_TO_MEALS.get(tag, []))
    allowed = [m for m, _ in MEAL_SPLIT if m in meals]
    return allowed or [m for m, _ in MEAL_SPLIT]


def _counts_as_vegetable(food: dict) -> bool:
    """Rau thật (không phải gia vị như tỏi, gừng, hành lá) mới tính vào mức rau tối thiểu."""
    return food["category"] == "vegetable" and _max_units(food) >= 1.0


def _solve(macro_targets: dict, daily_budget: float, food_db: list,
           enforce_budget: bool, strict: bool, spend_target: float | None = None,
           preferred_foods: list | None = None):
    """Giải 1 lần. Biến x[(món, bữa)] = số unit của món trong bữa đó.
    strict=True: thêm biến nhị phân + ràng buộc đa dạng/cấu trúc bữa (MILP).
    spend_target: nếu có thì tối thiểu hóa độ lệch chi phí so với target.
    preferred_foods: danh sách món yêu thích được ưu tiên chọn trong hàm mục tiêu."""
    foods = _usable_foods(food_db)
    prob = pulp.LpProblem("diet_problem", pulp.LpMinimize)

    x, y, z = {}, {}, {}
    for i, food in enumerate(foods):
        name = food["name"]
        ub = _max_units(food)
        meals = _allowed_meals(food)
        for m in meals:
            j = [mm for mm, _ in MEAL_SPLIT].index(m)
            x[(name, m)] = pulp.LpVariable(f"x_{i}_{j}", lowBound=0, upBound=ub)
        # tổng cả ngày của 1 món không vượt trần khẩu phần
        prob += pulp.lpSum(x[(name, m)] for m in meals) <= ub

        if strict:
            lo = min(MIN_UNITS_IF_USED, ub)

            for m in meals:
                j = [mm for mm, _ in MEAL_SPLIT].index(m)
                y[(name, m)] = pulp.LpVariable(f"y_{i}_{j}", cat="Binary")
                prob += x[(name, m)] <= ub * y[(name, m)]
                prob += x[(name, m)] >= lo * y[(name, m)]
            z[name] = pulp.LpVariable(f"z_{i}", cat="Binary")  # món có xuất hiện trong ngày
            for m in meals:
                prob += z[name] >= y[(name, m)]
            prob += z[name] <= pulp.lpSum(y[(name, m)] for m in meals)
            cap = MAX_MEALS_PER_FOOD.get(food["category"])
            if cap:
                prob += pulp.lpSum(y[(name, m)] for m in meals) <= cap


    by_name = {f["name"]: f for f in foods}

    def day_sum(field):
        return pulp.lpSum(by_name[n][field] * v for (n, _), v in x.items())

    cost = pulp.lpSum(by_name[n]["price_per_unit"] * v for (n, _), v in x.items())

    # Mục tiêu
    if spend_target is None:
        if preferred_foods:
            pref_set = set(preferred_foods)
            # Ưu tiên món yêu thích bằng cách giảm nhẹ chi phí tương đối trong hàm mục tiêu
            weighted_cost = pulp.lpSum(
                (by_name[n]["price_per_unit"] * (0.75 if n in pref_set else 1.0)) * v
                for (n, _), v in x.items()
            )
            prob += weighted_cost
        else:
            prob += cost
    else:
        gap = pulp.LpVariable("spend_gap", lowBound=0)
        prob += cost - spend_target <= gap
        prob += spend_target - cost <= gap
        if preferred_foods:
            pref_bonus = pulp.lpSum(
                0.01 * by_name[n]["price_per_unit"] * v
                for (n, _), v in x.items() if n in preferred_foods
            )
            prob += gap + 0.001 * cost - pref_bonus
        else:
            prob += gap + 0.001 * cost  # phá hòa: ưu tiên rẻ hơn khi gap bằng nhau

    # Macro cả ngày: tối thiểu = target, tối đa = MACRO_UPPER_RATIO * target
    for key, field in (("protein_g", "protein"), ("fat_g", "fat"), ("carb_g", "carbs")):
        total = day_sum(field)
        min_factor = 1.0 if strict else 0.95
        prob += total >= macro_targets[key] * min_factor
        prob += total <= macro_targets[key] * MACRO_UPPER_RATIO

    # Calories cả ngày +-10%
    total_calories = day_sum("calories")
    prob += total_calories <= macro_targets["calories"] * (1 + CALORIE_TOLERANCE)
    prob += total_calories >= macro_targets["calories"] * (1 - CALORIE_TOLERANCE)

    # Trần/sàn theo nhóm (bỏ qua nếu nhóm không có món, ví dụ bị lọc dị ứng)
    for cat, cap in CATEGORY_GROUP_MAX_UNITS.items():
        items = [v for (n, _), v in x.items() if by_name[n]["category"] == cat]
        if items:
            prob += pulp.lpSum(items) <= cap
    for cat, need in CATEGORY_GROUP_MIN_UNITS.items():
        items = [v for (n, _), v in x.items() if by_name[n]["category"] == cat]
        if items:
            max_possible = sum(_max_units(f) for f in foods if f["category"] == cat)
            prob += pulp.lpSum(items) >= min(need, max_possible)

    # Rau tối thiểu (chỉ rau "thật")
    veg_vars = [v for (n, _), v in x.items() if _counts_as_vegetable(by_name[n])]
    if veg_vars:
        veg_cap = sum(_max_units(f) for f in foods if _counts_as_vegetable(f))
        prob += pulp.lpSum(veg_vars) >= min(MIN_VEGETABLE_G / 100, veg_cap)

    # Calo từng bữa theo MEAL_SPLIT: Luôn ràng buộc ở cả strict và fallback để không bị dồn calo
    meal_tol = MEAL_CAL_TOLERANCE if strict else 0.30
    for meal_name, ratio in MEAL_SPLIT:
        meal_cal = pulp.lpSum(
            by_name[n]["calories"] * v for (n, m), v in x.items() if m == meal_name
        )
        target = macro_targets["calories"] * ratio
        prob += meal_cal <= target * (1 + meal_tol)
        prob += meal_cal >= target * (1 - meal_tol)

    if strict:
        # Mỗi bữa phải có đủ vai trò (tinh bột, đạm, rau...)
        for meal_name, reqs in MEAL_REQUIRED.items():
            for cats, need in reqs:
                items = [y[(n, m)] for (n, m) in y
                         if m == meal_name and by_name[n]["category"] in cats]
                if items:
                    prob += pulp.lpSum(items) >= min(need, len(items))

        # Đa dạng cả ngày
        prob += pulp.lpSum(z.values()) >= min(MIN_DISTINCT_TOTAL, len(z))
        for cat, need in CATEGORY_MIN_DISTINCT.items():
            in_cat = [z[f["name"]] for f in foods if f["category"] == cat and f["name"] in z]
            if in_cat:
                prob += pulp.lpSum(in_cat) >= min(need, len(in_cat))
    else:
        # Khi ở fallback (strict=False), đảm bảo mỗi bữa luôn có đủ vai trò cơ bản, không bị bữa 0 calo
        for meal_name, reqs in MEAL_REQUIRED.items():
            for cats, _ in reqs:
                cat_vars = [v for (n, m), v in x.items() if m == meal_name and by_name[n]["category"] in cats]
                if cat_vars:
                    prob += pulp.lpSum(cat_vars) >= 0.2

    if enforce_budget:
        prob += cost <= daily_budget

    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=15))

    status = pulp.LpStatus[prob.status]
    # x_values: {tên món: {tên bữa: số unit}}
    x_values = {}
    for (name, meal), var in x.items():
        x_values.setdefault(name, {})[meal] = var.value() or 0.0
    total_cost = sum(
        by_name[n]["price_per_unit"] * sum(per_meal.values())
        for n, per_meal in x_values.items()
    )
    return status, x_values, total_cost


def _build_and_solve(macro_targets: dict, daily_budget: float, food_db: list,
                     enforce_budget: bool = True, preferred_foods: list | None = None):
    """Giữ nguyên chữ ký & kiểu trả về (status, x_values, total_cost);
    x_values giờ là {món: {bữa: unit}} thay vì {món: unit} (chỉ dùng nội bộ với _build_meals)."""
    status, x_val, cost = "Infeasible", {}, 0.0
    for strict in (True, False):  # lần 2 = fallback không có ràng buộc đa dạng/cấu trúc bữa
        status, x_val, cost = _solve(macro_targets, daily_budget, food_db,
                                     enforce_budget, strict, preferred_foods=preferred_foods)  # pha 1: min cost
        if status != "Optimal":
            continue

        if enforce_budget and strict:  # pha 2: dùng ngân sách có chủ đích
            target = min(BUDGET_UTILIZATION * daily_budget, MAX_SPEND_OVER_MIN * cost)
            s2, x2, c2 = _solve(macro_targets, daily_budget, food_db,
                                enforce_budget, strict, spend_target=target,
                                preferred_foods=preferred_foods)
            if s2 == "Optimal":
                return s2, x2, c2
        return status, x_val, cost
    return status, x_val, cost


def _build_meals(x_values: dict, food_db: list) -> list:
    """Đọc trực tiếp lượng từng món theo từng bữa từ solver (không chia tỷ lệ nữa)."""
    by_name = {food["name"]: food for food in food_db}
    meals = []
    for meal_name, _ in MEAL_SPLIT:
        ingredients = []
        meal_calories = meal_protein = meal_fat = meal_carb = meal_cost = 0.0
        for name, per_meal in x_values.items():
            units = per_meal.get(meal_name, 0)
            if not units or units < 0.01:
                continue
            food = by_name[name]
            amount_g = units * 100
            if amount_g < 1:
                continue
            cost = food["price_per_unit"] * units
            ingredients.append({
                "name": name,
                "amount_g": round(amount_g, 1),
                "cost": round(cost, 0),
            })
            meal_calories += food["calories"] * units
            meal_protein += food["protein"] * units
            meal_fat += food["fat"] * units
            meal_carb += food["carbs"] * units
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

def _try_solve_saver(macro_targets: dict, daily_budget: float, food_db: list, preferred_foods: list | None = None):
    """Thử tìm giải pháp cứu vãn (Saver Plan) trong ngân sách hiện tại bằng cách
    tự động điều chỉnh nhẹ 15-25% chỉ tiêu dinh dưỡng nhưng vẫn giữ mức an toàn."""
    for scale in [0.85, 0.80, 0.75]:
        scaled_targets = {
            "calories": macro_targets["calories"] * scale,
            "protein_g": macro_targets["protein_g"] * scale,
            "fat_g": macro_targets["fat_g"] * scale,
            "carb_g": macro_targets["carb_g"] * scale,
        }
        status, x_val, cost = _build_and_solve(scaled_targets, daily_budget, food_db, enforce_budget=True, preferred_foods=preferred_foods)
        if status == "Optimal":
            return scale, x_val, cost
    return None, None, None


def optimize_meal_plan(macro_targets: dict, budget: dict, food_db: list, preferred_foods: list | None = None) -> dict:
    """
    macro_targets: {"calories", "protein_g", "fat_g", "carb_g"} - target NGÀY (từ Agent 1)
    budget: {"amount", "period"} - "weekly" | "monthly"
    food_db: list các dict {"name","category","price_per_unit","calories","protein","carbs","fat",...}
             ĐÃ lọc dị ứng từ trước khi gọi hàm này.
    preferred_foods: list các tên món ăn người dùng yêu thích để ưu tiên đưa vào thực đơn.

    Trả về dict khớp MealPlanResponse (feasible, meals, total_cost_estimate, message, suggested_budget, scenarios).
    """
    daily_budget = _daily_budget(budget)
    days = PERIOD_DAYS[budget["period"]]
    p_unit = "tuần" if budget["period"] == "weekly" else "tháng"

    status, x_values, daily_cost = _build_and_solve(macro_targets, daily_budget, food_db, enforce_budget=True, preferred_foods=preferred_foods)

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
    # (b) macro target không thể đạt được dù food_db/giới hạn khẩu phần có rộng rãi thế nào
    status_relaxed, x_relaxed, min_cost = _build_and_solve(
        macro_targets, daily_budget, food_db, enforce_budget=False, preferred_foods=preferred_foods
    )

    if status_relaxed == "Optimal":
        suggested_total_budget = round(min_cost * days, 0)
        needed_more = max(suggested_total_budget - budget["amount"], 0)

        # Tự phản biện tìm Kịch bản Tiết kiệm trong ngân sách hiện tại
        scale_found, x_saver, saver_cost = _try_solve_saver(macro_targets, daily_budget, food_db, preferred_foods=preferred_foods)
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
# _try_solve_saver và optimize_meal_plan: GIỮ NGUYÊN 100% như bản trước,
# không cần sửa dòng nào (chúng chỉ gọi _build_and_solve và _build_meals).