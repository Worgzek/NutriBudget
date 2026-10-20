from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.schemas import (
    NutritionRequest, NutritionResponse,
    MealPlanRequest, MealPlanResponse,
)
from app.agents.setup import run_agent_turn, session_service, APP_NAME, USER_ID
from app.agents.chef import enhance_meals_with_chef
from app.db import DATABASE_URL
from app.planner.optimizer import optimize_meal_plan
from app.planner.query import get_food_db

import os
import psycopg2

app = FastAPI(
    title="NutriBudget API",
    description="API cho NutriBudget - tính macro và gợi ý thực đơn theo ngân sách",
    version="2.0.0",
)


def _fallback_meal_plan(session, budget, allergens: list[str], rotation_exclusions: list[str]) -> dict:
    """Chạy Planner xác định khi Agent không tạo kết quả đúng lượt request hiện tại."""
    food_db = get_food_db(exclude_allergens=allergens)
    if rotation_exclusions:
        food_db = [food for food in food_db if food["name"] not in rotation_exclusions]

    if not food_db:
        result = {
            "feasible": False,
            "meals": [],
            "total_cost_estimate": None,
            "message": "Không còn thực phẩm phù hợp sau khi áp dụng các lựa chọn hiện tại.",
            "suggested_budget": None,
            "scenarios": None,
        }
    else:
        result = optimize_meal_plan(
            macro_targets=session.state["macro_targets"], budget=budget, food_db=food_db
        )
        if result.get("feasible") and result.get("meals"):
            meals, advice, _ = enhance_meals_with_chef(result["meals"])
            result["meals"] = meals
            if advice:
                result["ai_advice"] = advice

    session.state["meal_plan_budget"] = budget
    session.state["meal_plan_filters"] = {
        "allergens": allergens,
        "rotation_exclusions": rotation_exclusions,
    }
    session.state["meal_plan_result"] = result
    session.state["agent_trace"] = [{
        "actor": "Meal Planner",
        "action": "fallback_solver",
        "status": "completed",
        "summary": "Đã chạy Solver dự phòng với dữ liệu đã xác nhận cho lượt này.",
    }]
    return result

_DEFAULT_ORIGINS = (
    "http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500"
    "https://christine-balmy-tasha.ngrok-free.dev"
)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _frontend_dir() -> Path | None:
    env_dir = os.getenv("FRONTEND_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir))
    here = Path(__file__).resolve()
    candidates.extend([
        here.parents[2] / "frontend",  # project/frontend khi chạy local từ backend/
        Path("/frontend"),             # docker-compose mount
    ])
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


@app.get("/health")
def health():
    """Healthcheck Docker"""
    return {"status": "ok"}


@app.get("/health/db")
def check_db_connection():
    """Healthcheck DB"""
    try:
        connection = psycopg2.connect(DATABASE_URL)
        cursor = connection.cursor()
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        cursor.close()
        connection.close()
        return {"status": "success", "database_version": db_version[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")


@app.post("/api/v1/nutrition/macros", response_model=NutritionResponse)
async def get_nutrition_macros(payload: NutritionRequest):
    session_id = str(uuid4())

    message = (
        f"Thông tin cá nhân: chiều cao {payload.height_cm} cm, cân nặng "
        f"{payload.weight_kg} kg, {payload.age} tuổi, giới tính {payload.gender}, "
        f"mức vận động {payload.activity_level}, mục tiêu {payload.goal}."
    )
    if payload.notes:
        message += f" Ghi chú của người dùng: {payload.notes}"

    final_text, session = await run_agent_turn(session_id, message)

    macro_targets = session.state.get("macro_targets")
    if macro_targets is None:
        raise HTTPException(
            status_code=500,
            detail="Agent không trả về kết quả tính toán macro.",
        )

    # Đối chiếu tham số agent đã đưa vào tool với request gốc - phát hiện LLM chép sai số
    used = session.state.get("nutrition_inputs") or {}
    expected = {
        "weight_kg": payload.weight_kg, "height_cm": payload.height_cm, "age": payload.age,
        "gender": payload.gender, "activity_level": payload.activity_level,
        "goal": payload.goal,
    }
    if any(used.get(k) != v for k, v in expected.items()):
        raise HTTPException(
            status_code=500,
            detail="Agent đã gọi tool với tham số sai lệch so với dữ liệu người dùng nhập.",
        )

    return NutritionResponse(
        session_id=session_id,
        calories=macro_targets["calories"],
        protein_g=macro_targets["protein_g"],
        fat_g=macro_targets["fat_g"],
        carb_g=macro_targets["carb_g"],
        explanation=final_text or "Đã tính xong chỉ tiêu dinh dưỡng của bạn.",
        warning=session.state.get("warnings"),
        agent_trace=session.state.get("agent_trace", []),
    )


@app.post("/api/v1/meal-plan", response_model=MealPlanResponse)
async def get_meal_plan(payload: MealPlanRequest):
    existing = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=payload.session_id
    )
    if existing is None or existing.state.get("macro_targets") is None:
        raise HTTPException(
            status_code=404,
            detail="Session không tồn tại hoặc đã hết hạn. Vui lòng làm lại từ bước 1.",
        )

    selected_allergens = sorted(set(payload.allergens))
    rotation_exclusions = sorted(set(payload.rotation_exclusions))
    # Dữ liệu có cấu trúc từ UI là nguồn chính thức để tool dùng lại.
    # Không phụ thuộc vào việc LLM lặp đúng từng phần tử khi gọi hàm.
    existing.state["meal_plan_requested_allergens"] = selected_allergens
    existing.state["meal_plan_rotation_exclusions"] = rotation_exclusions
    message = (
        f"Ngân sách {payload.budget.amount:.0f} VNĐ theo {payload.budget.period}. "
        f"Nhóm cần loại trừ đã được người dùng chọn: "
        f"{', '.join(selected_allergens) if selected_allergens else 'không có'}; "
        "hãy truyền đúng danh sách này vào tool."
    )
    if payload.notes:
        message += f" Ghi chú của người dùng: {payload.notes}"
    if rotation_exclusions:
        message += " Người dùng muốn đổi thực đơn; ưu tiên không dùng lại: " + ", ".join(rotation_exclusions) + "."

    try:
        final_text, session = await run_agent_turn(payload.session_id, message)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("run_agent_turn failed: %s, falling back to deterministic solver", exc)
        session = existing

    result = session.state.get("meal_plan_result")
    used_budget = session.state.get("meal_plan_budget") or {}
    used_filters = session.state.get("meal_plan_filters") or {}
    if (
        result is None
        or used_budget.get("period") != payload.budget.period
        or abs(used_budget.get("amount", -1) - payload.budget.amount) > 0.5
        or used_filters.get("allergens", []) != selected_allergens
        or used_filters.get("rotation_exclusions", []) != rotation_exclusions
    ):
        result = _fallback_meal_plan(
            session=session,
            budget={"amount": payload.budget.amount, "period": payload.budget.period},
            allergens=selected_allergens,
            rotation_exclusions=rotation_exclusions,
        )

    return MealPlanResponse(
        **result,
        agent_trace=session.state.get("agent_trace", []),
    )


FRONTEND_DIR = _frontend_dir()
if FRONTEND_DIR is not None:
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
