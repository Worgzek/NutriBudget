# NutriBudget Backend — Nutrition & Meal Planning Tools

Tài liệu kỹ thuật cho phần đã build: 2 tool thuần (chưa có LLM) phục vụ Nutrition Agent
và Meal Planning Agent, cùng 2 API endpoint nối vào chúng. Đây là nền tảng trước khi
thêm lớp agent (LLM + LangGraph) ở bước tiếp theo.

## 1. Cấu trúc thư mục

```
backend/
├── app/
│   ├── main.py                      # FastAPI app, 2 route
│   ├── schemas.py                   # Pydantic models (request/response)
│   ├── db.py                        # DATABASE_URL dùng chung
│   ├── nutrition/
│   │   ├── calculator.py            # calculate_bmr/tdee/macros, calculate_nutrition()
│   │   └── validators.py            # validate_profile() và các hàm validate riêng lẻ
│   └── meal_planning/
│       ├── optimizer.py             # optimize_meal_plan() - PuLP
│       ├── allergen_matcher.py      # extract_allergens_from_notes() - keyword match tạm
│       └── repository.py            # get_food_db() - đọc + lọc dị ứng từ Postgres
└── db/
    ├── seed_foods.sql                # 17 thực phẩm mẫu, insert vào bảng foods
    └── seed_foods.py                 # bản Python song song, dùng để test không cần DB
```

## 2. API Reference

### `POST /api/v1/nutrition/macros`

Tính BMR → TDEE → calo mục tiêu → macro, theo công thức Mifflin-St Jeor.

**Request**
```json
{
  "height_cm": 170, "weight_kg": 60, "age": 20,
  "gender": "male", "activity_level": "moderate", "goal": "muscle_gain",
  "notes": "tập gym 4 buổi/tuần"
}
```

**Response (200)**
```json
{
  "calories": 2672.6, "protein_g": 120.0, "fat_g": 74.2, "carb_g": 381.1,
  "explanation": "... (câu cố định tạm thời, chưa dùng LLM)",
  "warning": null
}
```

`warning` là `list[str]` (không phải `str`), có thể chứa nhiều cảnh báo cùng lúc.

### `POST /api/v1/meal-plan`

Lọc dị ứng từ `notes` → lọc `food_db` → giải bài toán tối ưu (PuLP) → trả thực đơn.

**Request**
```json
{
  "macro_targets": {"calories": 2400, "protein_g": 140, "fat_g": 70, "carb_g": 260},
  "budget": {"amount": 2000000, "period": "monthly"},
  "notes": "dị ứng hải sản, ưu tiên món chay"
}
```

**Response (200, feasible)**
```json
{
  "feasible": true,
  "meals": [
    {"meal_name": "Bữa sáng", "ingredients": [...], "macros": {...}, "meal_cost": 123456}
  ],
  "total_cost_estimate": 929182,
  "message": null,
  "suggested_budget": null
}
```

**Response (200, infeasible)**
```json
{
  "feasible": false,
  "meals": [],
  "total_cost_estimate": null,
  "message": "Với ngân sách hiện tại, chưa đủ để đạt chỉ tiêu dinh dưỡng...",
  "suggested_budget": 929182
}
```

`feasible: false` luôn trả HTTP 200 — đây là kết quả nghiệp vụ hợp lệ, không phải lỗi hệ thống.

## 3. Quyết định thiết kế quan trọng

### Validate ở tầng nào, do ai chịu trách nhiệm
- Pydantic (`schemas.py`, dùng `Literal`) chặn giá trị sai ngay ở request — lớp đầu tiên.
- `validators.py` validate lại lần 2 trong `calculate_nutrition()` (phòng khi hàm được gọi
  trực tiếp ngoài route, không qua Pydantic) — không âm thầm fallback khi input sai,
  luôn `raise ValueError` → route convert thành HTTP 400.

### Cảnh báo an toàn (Nutrition Agent) — toàn bộ là code cứng, không qua LLM
Thứ tự kiểm tra trong `calculate_macros()`:
1. Tuổi < 18 → luôn cảnh báo (không chặn tính toán, không đổi goal)
2. Calo thấp hơn ngưỡng an toàn theo giới tính (1500 nam / 1200 nữ)
3. BMI < 18.5 (thiếu cân) — áp dụng mọi goal, không riêng `weight_loss`
4. BMI ≥ 30 (béo phì) khi goal là `muscle_gain`

Nhiều cảnh báo có thể xảy ra cùng lúc (vd: tuổi vị thành niên + BMI thấp) — `warnings`
là list, gộp tất cả, không loại trừ lẫn nhau.

### Dị ứng — lọc bằng code, trích xuất tạm bằng keyword
- `allergen_matcher.py`: match từ khóa thô trong `notes` → danh sách allergen key.
  **Đã biết có false positive** (vd: "sữa chua là món tôi thích" bị gắn nhầm dị ứng sữa) —
  đây là giải pháp tạm, thiên về an toàn (thà lọc nhầm còn hơn bỏ sót), sẽ thay bằng LLM.
- `repository.py`: lọc thật sự xảy ra ở SQL (`WHERE NOT (allergen_tags && %s)`), không
  phải ở LLM hay ở optimizer — đảm bảo không sót dù bước trích xuất có sai.

### `optimize_meal_plan()` — bài toán Diet Problem (linear programming, PuLP)
- Tính cho **1 ngày**; budget (tuần/tháng) quy đổi về budget/ngày trước khi đưa vào solver.
- Biến quyết định: số đơn vị 100g mỗi thực phẩm, giới hạn tối đa 4 đơn vị (400g/ngày/loại).
- Ràng buộc: protein/fat/carb ≥ target; calories trong ±10% target; chi phí ≤ budget/ngày;
  rau (category `vegetable`) ≥ 150g/ngày (thêm sau khi phát hiện solver bỏ hẳn rau nếu
  không ép buộc, vì rau không giúp tối ưu chi phí).
- Khi infeasible, tự giải lại lần 2 (bỏ ràng buộc budget) để phân biệt: ngân sách thấp
  (có `suggested_budget`) vs. mục tiêu dinh dưỡng bất khả thi dù tiền bao nhiêu
  (không có `suggested_budget`, message khác).
- Kết quả 1 ngày chia 3 bữa theo tỷ lệ cố định: sáng 25% / trưa 40% / tối 35% — cả 3 bữa
  dùng chung 1 tổ hợp thực phẩm, chỉ khác khối lượng (đánh đổi đã chọn cho MVP, có thể
  trông lặp lại khi demo).

### `PuLP` — cần ghim phiên bản
`pip install pulp` mặc định lấy bản mới nhất (4.0.0), là bản viết lại gần như toàn bộ
(core chuyển sang Rust), **đổi hẳn cách tạo `LpVariable`**, không tương thích với cú pháp
cổ điển dùng trong code này. Bắt buộc ghim `pulp==2.8.0` trong `requirements.txt`.

### CORS & `DATABASE_URL`
- `allow_origins=["*"]` cùng `allow_credentials=True` xung đột theo chuẩn CORS (trình
  duyệt tự chặn response) — origin đọc từ biến môi trường `ALLOWED_ORIGINS`.
- `DATABASE_URL` không có default ngầm — thiếu biến môi trường sẽ `raise RuntimeError`
  ngay lúc khởi động app, thay vì âm thầm thử kết nối sai và lỗi khó hiểu về sau.

## 4. Giới hạn đã biết / việc còn lại

- `explanation` (Nutrition) và lời diễn giải thực đơn (Meal Planning) vẫn là câu mẫu cố
  định — LLM sẽ thay thế, chưa làm.
- `allergen_matcher.py` cần thay bằng LLM trước khi launch thật (xem false positive ở trên).
- `optimize_meal_plan()` dùng ngân sách chung, rau chung — chưa cá nhân hóa theo sở thích
  trong `notes` (vd: "ưu tiên món chay" hiện chưa được xử lý).
- Chưa có Supervisor/LangGraph nối 2 route thành 1 luồng agent thật — bước tiếp theo.
- Chưa có test chính thức (`pytest`) cho `optimize_meal_plan()` — mới test tay qua REPL
  và qua Postgres thật.

## 5. Cách chạy thử

```bash
# Seed DB (1 lần)
psql -h localhost -U postgres -d nutribudget -f db/create_tables.sql
psql -h localhost -U postgres -d nutribudget -f db/seed_foods.sql

# Chạy app
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/nutribudget"
uvicorn app.main:app --reload

# Test qua Swagger
open http://localhost:8000/docs
```
