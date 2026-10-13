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
from app.db import DATABASE_URL

import os
import psycopg2

app = FastAPI(
    title="NutriBudget API",
    description="API cho NutriBudget - tính macro và gợi ý thực đơn theo ngân sách",
    version="2.0.0",
)

_DEFAULT_ORIGINS = (
    "http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500"
)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cho phép mọi nguồn gọi vào
    allow_credentials=True,
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

    message = f"Ngân sách {payload.budget.amount:.0f} VNĐ theo {payload.budget.period}."
    if payload.notes:
        message += f" Ghi chú của người dùng: {payload.notes}"

    final_text, session = await run_agent_turn(payload.session_id, message)

    result = session.state.get("meal_plan_result")
    used_budget = session.state.get("meal_plan_budget") or {}
    if (
        result is None
        or used_budget.get("period") != payload.budget.period
        or abs(used_budget.get("amount", -1) - payload.budget.amount) > 0.5
    ):
        # Không có kết quả, hoặc kết quả là của lượt trước / tool bị gọi với ngân sách sai
        raise HTTPException(
            status_code=500,
            detail="Agent không trả về kết quả thực đơn khớp với ngân sách đã nhập.",
        )

    return MealPlanResponse(**result)


FRONTEND_DIR = _frontend_dir()
if FRONTEND_DIR is not None:
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")