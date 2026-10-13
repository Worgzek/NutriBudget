"""
app/agents/setup.py

Định nghĩa 3 agent ADK (supervisor + 2 sub-agent), session service và runner.
Route trong main.py chỉ cần gọi run_agent_turn(), không biết chi tiết ADK.

Cần biến môi trường GOOGLE_API_KEY (lấy miễn phí từ Google AI Studio).
"""

import os
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.tools import run_nutrition_calculation, generate_meal_plan

APP_NAME = "nutribudget"
USER_ID = "guest"  # MVP không có tài khoản - ADK yêu cầu user_id nên dùng giá trị cố định
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")



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
này phù hợp với mục tiêu của người dùng. Nếu kết quả có warnings, PHẢI nhắc lại rõ
ràng từng cảnh báo, không được bỏ qua hay nói nhẹ đi. Nếu có ghi chú từ người dùng,
có thể lồng vào lời khuyên nhưng KHÔNG được thay đổi bất kỳ con số nào.

KHÔNG tự tính toán hay ước lượng số liệu - luôn dùng tool.
""",
    tools=[run_nutrition_calculation],
)


meal_planning_agent = Agent(
    name="meal_planning_agent",
    model=MODEL,
    description="Tạo thực đơn tối ưu chi phí theo ngân sách, dựa trên chỉ tiêu "
                "dinh dưỡng đã tính trước đó.",
    instruction="""
Bạn nhận ngân sách và ghi chú của người dùng (ghi chú có thể chứa thông tin dị ứng
hoặc sở thích ăn uống).

Bước 1 - Đọc kỹ ghi chú, xác định người dùng có THỰC SỰ bị dị ứng hoặc không ăn được
nhóm nào trong 5 nhóm sau không: seafood (hải sản), dairy (sữa), peanut (đậu phộng),
gluten, egg (trứng). Chỉ tính là dị ứng khi người dùng nói rõ họ bị dị ứng / không ăn
được. KHÔNG suy diễn dị ứng từ việc họ chỉ nhắc đến, khen, hoặc nói thích món đó.
Nếu nghi ngờ, ưu tiên an toàn (coi là có dị ứng).

Bước 2 - Gọi tool generate_meal_plan với budget_amount, budget_period và allergens
(danh sách nhóm dị ứng xác định được, rỗng [] nếu không có).

Bước 3 - Dựa trên kết quả tool:
- feasible = true: viết 2-3 câu tiếng Việt giới thiệu thực đơn tự nhiên, nêu tổng chi phí.
- feasible = false: giải thích rõ lý do bằng tiếng Việt theo message và suggested_budget
  trong kết quả, gợi ý người dùng tăng ngân sách hoặc điều chỉnh mục tiêu.
- Tool trả về trường "error": báo lại lỗi đó, không tự bịa thực đơn.

KHÔNG tự bịa thực đơn hay số liệu - luôn dùng tool.
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
runner = Runner(agent=supervisor, app_name=APP_NAME, session_service=session_service)


async def run_agent_turn(session_id: str, message_text: str, max_retries: int = 3):
    """Chạy 1 lượt hội thoại qua supervisor, trả về (final_text, session).

    - Tạo session mới nếu session_id chưa tồn tại.
    - Có cơ chế retry khi gặp lỗi 503 / quá tải tạm thời từ LLM API.
    - Số liệu có cấu trúc đọc từ session.state (do tool ghi), final_text chỉ dùng
      làm phần giải thích bằng ngôn ngữ tự nhiên.
    """
    import asyncio

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )

    content = types.Content(role="user", parts=[types.Part(text=message_text)])

    for attempt in range(max_retries):
        try:
            final_text = None
            async for event in runner.run_async(
                user_id=USER_ID, session_id=session_id, new_message=content
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    text = "".join(p.text for p in event.content.parts if p.text)
                    if text:
                        final_text = text

            # Lấy lại session mới nhất - state đã bị tool thay đổi trong lúc chạy
            session = await session_service.get_session(
                app_name=APP_NAME, user_id=USER_ID, session_id=session_id
            )
            return final_text, session
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))