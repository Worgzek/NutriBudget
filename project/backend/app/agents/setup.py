"""
app/agents/setup.py

Định nghĩa 3 agent ADK (supervisor + 2 sub-agent), session service và runner.
Route trong main.py chỉ cần gọi run_agent_turn(), không biết chi tiết ADK.

Cần biến môi trường GOOGLE_API_KEY (lấy miễn phí từ Google AI Studio).
"""

import logging
import os
import random
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.tools import run_nutrition_calculation, generate_meal_plan
from app.agents.model_fallback import model_candidates, is_retryable_error

APP_NAME = "nutribudget"
USER_ID = "guest"
logger = logging.getLogger(__name__)
MODEL = model_candidates()[0]



nutrition_agent = Agent(
    name="nutrition_agent",
    model=MODEL,
    description="Tính chỉ tiêu dinh dưỡng (calories, protein, fat, carb) cá nhân hóa "
                "từ thông tin cơ thể và mục tiêu của người dùng.",
    instruction="""
Bạn là chuyên gia dinh dưỡng. Khi nhận được thông tin cá nhân của người dùng
(chiều cao, cân nặng, tuổi, giới tính, mức vận động, mục tiêu), gọi tool
run_nutrition_calculation với ĐÚNG các giá trị người dùng cung cấp.

Sau khi có kết quả, viết 2-4 câu tiếng Việt giải thích dễ hiểu vì sao các con số
này phù hợp với mục tiêu của người dùng.

KHÔNG tự tính toán hay ước lượng số liệu - luôn dùng tool.
""",
    tools=[run_nutrition_calculation],
)


meal_planning_agent = Agent(
    name="meal_planning_agent",
    model=MODEL,
    description="Tạo và tự phản biện thực đơn tối ưu chi phí theo ngân sách và chỉ tiêu dinh dưỡng.",
    instruction="""
Bạn là Meal Planning Agent thông minh, am hiểu dinh dưỡng và giá cả thị trường sinh viên.
Bạn có năng lực TỰ SUY LUẬN, PHẢN BIỆN VÀ TỰ SỬA SAI (Self-Reflection & ReAct Loop).

Quy trình làm việc của bạn:

VÒNG 1 - Tối ưu ban đầu:
- Luôn gọi tool generate_meal_plan với budget_amount, budget_period và đúng danh sách allergens đã nhận.

VÒNG 2 - Quan sát (Observation), Tự phản biện (Reflection) & Tự sửa sai (Self-Correction):
Dựa trên kết quả trả về từ Vòng 1, bạn KHÔNG vội kết thúc ngay mà hãy tự đánh giá:

1. Trường hợp thiếu ngân sách (feasible = false):
   - Phân tích nguyên nhân: Ngân sách hiện tại có thể bị hụt vì danh mục còn chứa các món đắt tiền (như thịt bò, cá hồi, thịt vịt, dầu oliu...).
   - Hành động tự sửa sai: BẬT VÒNG LẶP GỌI LẠI tool generate_meal_plan lần 2 với:
     * max_price_per_unit: 18000 (hoặc 20000) để lọc bớt nguyên liệu giá cao.
     * reflection_note: "Phát hiện ngân sách chưa đủ, tự động giới hạn trần giá nguyên liệu để tối ưu sang nhóm đạm kinh tế (trứng, đậu phụ, cá rô phi, ức gà)."

2. Trường hợp khả thi (feasible = true):
   - Đánh giá mức độ hài hòa và đa dạng của các bữa ăn:
     * Kiểm tra xem có món đạm nào bị lặp lại ở cả 2 bữa (ví dụ: trưa trứng gà, tối lại trứng gà; hoặc trưa thịt lợn, tối lại thịt lợn) không?
     * Nếu thấy thực đơn bị đơn điệu: GỌI LẠI tool generate_meal_plan lần 2 với:
       * exclude_foods: [tên món bị lặp cần thay thế, ví dụ "Trứng gà"]
       * reflection_note: "Phát hiện món đạm bị trùng lặp giữa trưa và tối gây ngán, tự động đổi món đạm bữa khác để thực đơn phong phú hơn."

VÒNG 3 - Tổng kết và Diễn giải cho người dùng:
- Nếu feasible = true: Viết 2-4 câu tiếng Việt tự nhiên, nêu tổng chi phí và GIẢI THÍCH RÕ các bước bạn đã tự phản biện/điều chỉnh (ví dụ: đã chủ động lọc món đắt hoặc đã chống lặp món như thế nào).
- Nếu feasible = false (dù đã thử tối ưu tiết kiệm): Giải thích mức ngân sách tối thiểu ước tính và các kịch bản trong kết quả (Kịch bản Chuẩn & Kịch bản Tiết kiệm).
- KHÔNG tự bịa số liệu hay thực đơn ngoài kết quả tool.
""",
    tools=[generate_meal_plan],
)


supervisor = Agent(
    name="supervisor",
    model=MODEL,
    description="Điều phối giữa agent tính macro và agent lập thực đơn.",
    instruction="""
Bạn là điều phối viên. Nhìn nội dung tin nhắn để chọn đúng agent:
- Tin nhắn chứa thông tin cơ thể cá nhân (chiều cao, cân nặng, tuổi, giới tính, mức
  vận động, mục tiêu) -> chuyển cho nutrition_agent.
- Tin nhắn chứa ngân sách (tuần/tháng) -> chuyển cho meal_planning_agent.
Không tự trả lời nội dung chuyên môn, luôn chuyển cho agent phù hợp.
""",
    sub_agents=[nutrition_agent, meal_planning_agent],
)


session_service = InMemorySessionService()


def create_supervisor(model: str):
    """Create the same tool-constrained workflow with a selected Gemini model."""
    nutrition = Agent(
        name="nutrition_agent",
        model=model,
        description=nutrition_agent.description,
        instruction=nutrition_agent.instruction,
        tools=[run_nutrition_calculation],
    )
    meal_planning = Agent(
        name="meal_planning_agent",
        model=model,
        description=meal_planning_agent.description,
        instruction=meal_planning_agent.instruction,
        tools=[generate_meal_plan],
    )
    return Agent(
        name="supervisor",
        model=model,
        description=supervisor.description,
        instruction=supervisor.instruction,
        sub_agents=[nutrition, meal_planning],
    )


async def run_agent_turn(session_id: str, message_text: str, max_retries: int = 2):
    """Run the ADK workflow; retry transient failures, then try configured models."""
    import asyncio

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
    session.state["agent_trace"] = []

    content = types.Content(role="user", parts=[types.Part(text=message_text)])
    candidates = model_candidates()
    last_error = None
    trace = []
    actor_labels = {
        "supervisor": "Supervisor",
        "nutrition_agent": "Nutrition Agent",
        "meal_planning_agent": "Meal Planning Agent",
    }

    for model_index, model in enumerate(candidates):
        runner = Runner(
            agent=create_supervisor(model),
            app_name=APP_NAME,
            session_service=session_service,
        )
        for attempt in range(max_retries):
            try:
                final_text = None
                async for event in runner.run_async(
                    user_id=USER_ID, session_id=session_id, new_message=content
                ):
                    author = getattr(event, "author", None)
                    if author in actor_labels:
                        trace.append({
                            "actor": actor_labels[author],
                            "action": "route_request",
                            "status": "completed",
                            "summary": "Đã xử lý lượt yêu cầu.",
                        })
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            function_call = getattr(part, "function_call", None)
                            function_name = getattr(function_call, "name", None)
                            if function_name:
                                trace.append({
                                    "actor": "Agent",
                                    "action": function_name,
                                    "status": "called",
                                    "summary": "Đã gọi công cụ có cấu trúc.",
                                })
                    if event.is_final_response() and event.content and event.content.parts:
                        final_text = "".join(p.text for p in event.content.parts if p.text) or final_text

                session = await session_service.get_session(
                    app_name=APP_NAME, user_id=USER_ID, session_id=session_id
                )
                combined, seen = [], set()
                for item in trace + session.state.get("agent_trace", []):
                    key = (item.get("actor"), item.get("action"), item.get("status"))
                    if key not in seen:
                        combined.append(item)
                        seen.add(key)
                session.state["agent_trace"] = combined
                return final_text, session
            except Exception as error:
                last_error = error
                if not is_retryable_error(error):
                    raise
                if attempt + 1 < max_retries:
                    delay = min(2 ** attempt, 4) + random.uniform(0, 0.35)
                    logger.warning(
                        "Transient Gemini error on model %s; retry %d/%d in %.2fs: %s",
                        model, attempt + 1, max_retries - 1, delay, error,
                    )
                    await asyncio.sleep(delay)
                    continue
                break

        if model_index + 1 < len(candidates):
            next_model = candidates[model_index + 1]
            logger.warning("Switching Gemini model from %s to %s after transient errors", model, next_model)
            await asyncio.sleep(0.5 + random.uniform(0, 0.35))

    if last_error:
        raise last_error
    raise RuntimeError("Không có Gemini model nào được cấu hình.")
