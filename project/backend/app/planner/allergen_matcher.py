"""
app/meal_planning/allergen_matcher.py

Trích xuất nhóm dị ứng từ `notes` bằng keyword match thô - TẠM THỜI,
chưa dùng LLM. Sẽ thay bằng LLM ở bước sau (độ chính xác cao hơn,
hiểu được nhiều cách diễn đạt hơn).

GIỚI HẠN ĐÃ BIẾT (đã test thật, không phải đoán - cần nhớ khi thay bằng LLM):
- Không phân biệt được "dị ứng X" với "thích X"/"nhắc tới X" một cách trung tính.
  Test thực tế: "sữa chua là món tôi thích nhất" -> bị gắn nhầm dairy;
  "đạm từ cua đồng rất tốt" -> bị gắn nhầm seafood. Đây là false positive thật,
  không phải edge case lý thuyết.
- Không hiểu phủ định: "không bị dị ứng hải sản" vẫn match nhầm là CÓ dị ứng.
- Chỉ tiếng Việt có dấu đầy đủ + 1 số từ tiếng Anh cơ bản, không xử lý viết tắt/teencode.
- Hệ quả: lọc kiểu này chỉ nên xem là "ưu tiên an toàn hơn" (thà lọc nhầm còn hơn bỏ sót
  dị ứng thật), KHÔNG nên quảng cáo là chính xác - cần LLM thay thế trước khi launch thật.
"""

ALLERGEN_KEYWORDS = {
    "seafood": ["hải sản", "tôm", "mực", "cua", "sò", "nghêu", "seafood", "shrimp"],
    "dairy": ["sữa", "phô mai", "dairy", "milk", "lactose"],
    "peanut": ["đậu phộng", "lạc", "peanut"],
    "gluten": ["gluten", "lúa mì", "bột mì"],
    "egg": ["trứng", "egg"],
}


def extract_allergens_from_notes(notes) -> list:
    if not notes:
        return []
    notes_lower = notes.lower()
    found = []
    for allergen_key, keywords in ALLERGEN_KEYWORDS.items():
        if any(kw in notes_lower for kw in keywords):
            found.append(allergen_key)
    return found