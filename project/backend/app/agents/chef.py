"""
app/agents/chef.py

Chef Agent: Đóng vai trò Đầu bếp sinh viên Việt Nam.
Nhận danh sách nguyên liệu thô từ bộ giải quy hoạch tuyến tính (Optimizer)
và biến chúng thành tên món ăn quen thuộc, ngon miệng cùng mẹo chế biến
nhanh trong 10-15 phút phù hợp với điều kiện phòng trọ (nồi cơm điện, chảo chống dính).
"""

import json
import logging
import os
import random
import time
from google import genai
from google.genai import types
from app.agents.model_fallback import model_candidates, is_retryable_error

logger = logging.getLogger(__name__)

def get_genai_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def enhance_meals_with_chef(meals: list) -> tuple[list, str | None, str]:
    """Bổ sung dish_name và cooking_tip vào từng bữa ăn bằng Chef Agent.

    Args:
        meals: List các dict bữa ăn (chứa meal_name, ingredients, macros, meal_cost).

    Returns:
        tuple (meals_enhanced, chef_advice, status)
    """
    if not meals:
        return meals, None, "skipped_empty"

    client = get_genai_client()
    if not client:
        return meals, None, "fallback_no_api_key"

    # Tóm tắt nguyên liệu mỗi bữa để gửi cho LLM (chỉ gửi bữa có nguyên liệu thực tế)
    meal_summary = []
    for m in meals:
        ingredients = m.get("ingredients", [])
        if not ingredients:
            continue
        ing_list = [
            f"{i['name']} ({round(i['amount_g'])}g)"
            for i in ingredients
        ]
        meal_summary.append({
            "meal_name": m.get("meal_name", ""),
            "ingredients": ing_list,
        })

    if not meal_summary:
        return meals, None, "skipped_empty"

    prompt = f"""Bạn là Chef Agent - đầu bếp sinh viên Việt Nam am hiểu dinh dưỡng và đời sống sinh viên.
Dưới đây là thực đơn các bữa ăn trong ngày với danh sách nguyên liệu thô:
{json.dumps(meal_summary, ensure_ascii=False, indent=2)}

Nhiệm vụ của bạn:
1. Với mỗi bữa ăn, hãy sáng tạo tên món ăn Việt Nam đơn giản, ngắn gọn, quen thuộc (`dish_name`) kết hợp khéo léo các nguyên liệu trên.
2. Viết mẹo nấu siêu tốc 10-15 phút (`cooking_tip`).
3. Viết 1 lời khuyên ngắn (`chef_advice`) về mẹo đi chợ tiết kiệm hoặc sơ chế nhanh.

Yêu cầu định dạng đầu ra CHÍNH XÁC là JSON:
{{
  "meals": [
    {{
      "meal_name": "Tên bữa (ví dụ Bữa sáng)",
      "dish_name": "Tên món ăn (ví dụ: Trứng chiên hành thịt bằm kèm dưa chuột)",
      "cooking_tip": "Hướng dẫn chế biến 2-3 câu ngắn gọn..."
    }}
  ],
  "chef_advice": "Lời khuyên đầu bếp cho sinh viên..."
}}
Chỉ trả về JSON thuần, không bao gồm code block markdown.
"""

    try:
        data = None
        last_error = None
        for model_index, model in enumerate(model_candidates()):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.4,
                    ),
                )
                text = (response.text or "").strip()
                data = json.loads(text)
                break
            except Exception as error:
                last_error = error
                if not is_retryable_error(error):
                    raise
                if model_index + 1 >= len(model_candidates()):
                    raise
                next_model = model_candidates()[model_index + 1]
                logger.warning(
                    "Chef generation got a transient error on %s; switching to %s: %s",
                    model, next_model, error,
                )
                time.sleep(0.4 + random.uniform(0, 0.3))

        if data is None:
            raise last_error or RuntimeError("No Gemini model returned a response.")

        chef_meals = {item.get("meal_name"): item for item in data.get("meals", [])}
        chef_advice = data.get("chef_advice", "")

        for m in meals:
            m_name = m.get("meal_name")
            if m_name in chef_meals:
                m["dish_name"] = chef_meals[m_name].get("dish_name")
                m["cooking_tip"] = chef_meals[m_name].get("cooking_tip")

        return meals, chef_advice, "completed"
    except Exception as e:
        logger.warning(f"Chef Agent enhance failed: {e}. Falling back to raw ingredients.")
        return meals, None, "fallback_error"
