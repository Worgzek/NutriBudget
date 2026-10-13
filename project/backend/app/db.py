import os
 
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "Thiếu biến môi trường DATABASE_URL. Kiểm tra file .env hoặc docker-compose.yml."
    )