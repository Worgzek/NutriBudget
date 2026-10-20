import psycopg2
from app.db import DATABASE_URL


def get_food_db(exclude_allergens: list) -> list:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        query = """
            SELECT name, category, price_per_unit, calories, protein, carbs, fat,
                   allergen_tags, meal_types
            FROM foods
        """
        params = None
        if exclude_allergens:
            query += " WHERE NOT (allergen_tags && %s)"
            params = (exclude_allergens,)
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {
            "name": r[0],
            "category": r[1],
            "price_per_unit": float(r[2]),
            "calories": float(r[3]),
            "protein": float(r[4]),
            "carbs": float(r[5]),
            "fat": float(r[6]),
            "allergen_tags": r[7] or [],
            "meal_types": r[8] or [],
        }
        for r in rows
    ]