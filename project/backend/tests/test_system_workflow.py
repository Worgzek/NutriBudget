import os
import unittest
import requests
from app.nutrition.calculator import (
    calculate_bmr,
    calculate_tdee,
    calculate_bmi,
    calculate_calorie_target,
    calculate_macros,
    calculate_nutrition,
    generate_warnings,
)
from app.nutrition.validators import validate_profile
from app.planner.optimizer import optimize_meal_plan
from app.planner.query import get_food_db
from app.planner.allergen_matcher import extract_allergens_from_notes
from google.adk.tools.tool_context import ToolContext
from app.agents.tools import run_nutrition_calculation, generate_meal_plan

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")


class TestNutritionEngine(unittest.TestCase):
    """Kiểm thử deterministic nutrition engine: BMR, TDEE, macros, warnings, validators"""

    def test_bmr_calculation(self):
        # Male: 10*70 + 6.25*175 - 5*25 + 5 = 700 + 1093.75 - 125 + 5 = 1673.75
        bmr_male = calculate_bmr(weight_kg=70, height_cm=175, age=25, gender="male")
        self.assertAlmostEqual(bmr_male, 1673.75, places=2)

        # Female: 10*55 + 6.25*160 - 5*25 - 161 = 550 + 1000 - 125 - 161 = 1264.0
        bmr_female = calculate_bmr(weight_kg=55, height_cm=160, age=25, gender="female")
        self.assertAlmostEqual(bmr_female, 1264.0, places=2)

    def test_tdee_calculation(self):
        bmr = 1500.0
        self.assertAlmostEqual(calculate_tdee(bmr, "sedentary"), 1500.0 * 1.2)
        self.assertAlmostEqual(calculate_tdee(bmr, "light"), 1500.0 * 1.375)
        self.assertAlmostEqual(calculate_tdee(bmr, "moderate"), 1500.0 * 1.55)
        self.assertAlmostEqual(calculate_tdee(bmr, "heavy"), 1500.0 * 1.725)

    def test_calorie_targets_and_macros(self):
        tdee = 2000.0
        # weight_loss: 0.8 * 2000 = 1600 kcal
        cal_loss = calculate_calorie_target(tdee, "weight_loss")
        self.assertAlmostEqual(cal_loss, 1600.0)

        # muscle_gain: 1.1 * 2000 = 2200 kcal
        cal_gain = calculate_calorie_target(tdee, "muscle_gain")
        self.assertAlmostEqual(cal_gain, 2200.0)

        # maintain: 1.0 * 2000 = 2000 kcal
        cal_maint = calculate_calorie_target(tdee, "maintain")
        self.assertAlmostEqual(cal_maint, 2000.0)

        # Macros for muscle_gain, 60kg, 2200 kcal
        # Protein: 60 * 2.0 = 120g (480 kcal)
        # Fat: 2200 * 0.25 / 9 = 61.11g (550 kcal)
        # Carb: (2200 - 480 - 550) / 4 = 292.5g
        prot, fat, carb = calculate_macros(weight_kg=60, calories=2200, goal="muscle_gain")
        self.assertAlmostEqual(prot, 120.0, places=1)
        self.assertAlmostEqual(fat, 61.11, places=1)
        self.assertAlmostEqual(carb, 292.5, places=1)

    def test_warnings(self):
        # Underage warning
        warn_underage = generate_warnings(age=16, calories=2000, bmi=21.0, gender="male", goal="maintain")
        self.assertTrue(any("18 tuổi" in w for w in warn_underage))

        # Low calorie warning for male (< 1500 kcal)
        warn_low_cal = generate_warnings(age=25, calories=1300, bmi=21.0, gender="male", goal="weight_loss")
        self.assertTrue(any("thấp hơn ngưỡng tiêu chuẩn" in w for w in warn_low_cal))

        # Underweight warning (BMI < 18.5)
        warn_underweight = generate_warnings(age=25, calories=2000, bmi=17.5, gender="female", goal="maintain")
        self.assertTrue(any("18.5" in w for w in warn_underweight))

    def test_validators(self):
        # Valid profile
        profile = validate_profile(
            weight_kg=65, height_cm=170, age=22,
            gender=" male ", activity_level=" moderate ", goal=" muscle_gain "
        )
        self.assertEqual(profile["gender"], "male")
        self.assertEqual(profile["activity_level"], "moderate")
        self.assertEqual(profile["goal"], "muscle_gain")

        # Invalid age
        with self.assertRaises(ValueError):
            validate_profile(65, 170, 10, "male", "moderate", "muscle_gain")

        # Invalid height
        with self.assertRaises(ValueError):
            validate_profile(65, 0, 22, "male", "moderate", "muscle_gain")

        # Invalid gender
        with self.assertRaises(ValueError):
            validate_profile(65, 170, 22, "unknown", "moderate", "muscle_gain")


class TestMealPlannerOptimizer(unittest.TestCase):
    """Kiểm thử thuật toán giải bài toán thực đơn Diet Problem qua Linear Programming (PuLP)"""

    @classmethod
    def setUpClass(cls):
        cls.food_db = get_food_db(exclude_allergens=[])
        assert len(cls.food_db) > 0, "Database foods table must not be empty"

    def test_food_db_query_and_allergen_filter(self):
        all_foods = get_food_db(exclude_allergens=[])
        self.assertGreater(len(all_foods), 100)

        no_seafood = get_food_db(exclude_allergens=["seafood"])
        self.assertLess(len(no_seafood), len(all_foods))
        for food in no_seafood:
            self.assertNotIn("seafood", food["allergen_tags"])

    def test_optimizer_feasible_solution(self):
        macro_targets = {
            "calories": 2000.0,
            "protein_g": 100.0,
            "fat_g": 55.0,
            "carb_g": 275.0,
        }
        budget = {"amount": 500000.0, "period": "weekly"}

        result = optimize_meal_plan(macro_targets=macro_targets, budget=budget, food_db=self.food_db)
        self.assertTrue(result["feasible"])
        self.assertEqual(len(result["meals"]), 3)
        self.assertIsNotNone(result["total_cost_estimate"])
        self.assertLessEqual(result["total_cost_estimate"], budget["amount"])

        # Check meals have valid macros and ingredients
        meal_names = [m["meal_name"] for m in result["meals"]]
        self.assertEqual(meal_names, ["Bữa sáng", "Bữa trưa", "Bữa tối"])

    def test_optimizer_infeasible_budget(self):
        macro_targets = {
            "calories": 2500.0,
            "protein_g": 130.0,
            "fat_g": 70.0,
            "carb_g": 340.0,
        }
        # Budget 10,000 VND per week is impossible for 2500 kcal
        budget = {"amount": 10000.0, "period": "weekly"}

        result = optimize_meal_plan(macro_targets=macro_targets, budget=budget, food_db=self.food_db)
        self.assertFalse(result["feasible"])
        self.assertEqual(len(result["meals"]), 0)
        self.assertIsNotNone(result["suggested_budget"])
        self.assertIn("chưa đủ để đạt", result["message"])
        self.assertIsNotNone(result.get("scenarios"))


    def test_allergen_keyword_matcher(self):
        self.assertEqual(extract_allergens_from_notes(None), [])
        self.assertIn("seafood", extract_allergens_from_notes("Tôi dị ứng tôm và cua"))
        self.assertIn("egg", extract_allergens_from_notes("Không ăn được trứng"))
        self.assertIn("peanut", extract_allergens_from_notes("Dị ứng đậu phộng nặng"))
        self.assertIn("dairy", extract_allergens_from_notes("Tôi không uống được sữa bò"))
        self.assertIn("gluten", extract_allergens_from_notes("Bị bệnh celiac không ăn lúa mì"))


class TestAgentToolsState(unittest.TestCase):
    """Kiểm thử tính toàn vẹn trạng thái state session khi ADK tools thực thi"""

    def test_run_nutrition_calculation_updates_state(self):
        class DummyContext:
            def __init__(self):
                self.state = {}

        ctx = DummyContext()
        res = run_nutrition_calculation(
            weight_kg=65.0,
            height_cm=170.0,
            age=22,
            gender="male",
            activity_level="moderate",
            goal="muscle_gain",
            tool_context=ctx,
        )
        self.assertIn("nutrition_inputs", ctx.state)
        self.assertIn("macro_targets", ctx.state)
        self.assertEqual(ctx.state["nutrition_inputs"]["weight_kg"], 65.0)
        self.assertEqual(res["calories"], ctx.state["macro_targets"]["calories"])

    def test_generate_meal_plan_without_macro_targets_returns_error(self):
        class DummyContext:
            def __init__(self):
                self.state = {}

        ctx = DummyContext()
        res = generate_meal_plan(
            budget_amount=500000,
            budget_period="weekly",
            allergens=[],
            tool_context=ctx,
        )
        self.assertIn("error", res)
        self.assertIn("Chưa có macro_targets", res["error"])


class TestE2ESystemWorkflow(unittest.TestCase):
    """Kiểm thử toàn bộ luồng hệ thống HTTP End-to-End: Step 1 (Nutrition) -> Step 2 (Meal Plan)"""

    def test_01_health_checks(self):
        # GET /health
        res = requests.get(f"{BASE_URL}/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

        # GET /health/db
        res_db = requests.get(f"{BASE_URL}/health/db")
        self.assertEqual(res_db.status_code, 200)
        self.assertEqual(res_db.json()["status"], "success")
        self.assertIn("PostgreSQL", res_db.json()["database_version"])

    def test_02_nutrition_macros_validation_failure(self):
        # Negative weight
        payload = {
            "height_cm": 170,
            "weight_kg": -60,
            "age": 22,
            "gender": "male",
            "activity_level": "moderate",
            "goal": "muscle_gain"
        }
        res = requests.post(f"{BASE_URL}/api/v1/nutrition/macros", json=payload)
        self.assertEqual(res.status_code, 422)

    def test_03_full_system_workflow_successful(self):
        # Step 1: Calculate Nutrition Macros
        step1_payload = {
            "height_cm": 172.0,
            "weight_kg": 68.0,
            "age": 21,
            "gender": "male",
            "activity_level": "moderate",
            "goal": "muscle_gain",
            "notes": "Muốn tập gym tăng cơ"
        }
        res1 = requests.post(f"{BASE_URL}/api/v1/nutrition/macros", json=step1_payload)
        self.assertEqual(res1.status_code, 200, msg=f"Step 1 failed: {res1.text}")
        data1 = res1.json()

        self.assertIn("session_id", data1)
        session_id = data1["session_id"]
        self.assertGreater(data1["calories"], 1000)
        self.assertGreater(data1["protein_g"], 50)
        self.assertGreater(data1["fat_g"], 20)
        self.assertGreater(data1["carb_g"], 100)
        self.assertTrue(len(data1["explanation"]) > 20)

        # Step 2: Meal Plan with the session_id from Step 1
        step2_payload = {
            "session_id": session_id,
            "budget": {
                "amount": 600000.0,
                "period": "weekly"
            },
            "notes": "Tôi bị dị ứng hải sản"
        }
        res2 = requests.post(f"{BASE_URL}/api/v1/meal-plan", json=step2_payload)
        self.assertEqual(res2.status_code, 200, msg=f"Step 2 failed: {res2.text}")
        data2 = res2.json()

        self.assertTrue(data2["feasible"])
        self.assertEqual(len(data2["meals"]), 3)
        self.assertIsNotNone(data2["total_cost_estimate"])
        self.assertLessEqual(data2["total_cost_estimate"], 600000.0)

        # Verify no seafood ingredients
        for meal in data2["meals"]:
            for ing in meal["ingredients"]:
                # Check that seafood keywords are not in ingredient name
                name_lower = ing["name"].lower()
                self.assertNotIn("tôm", name_lower)
                self.assertNotIn("cua", name_lower)
                self.assertNotIn("mực", name_lower)
                self.assertNotIn("cá thu", name_lower)

    def test_04_meal_plan_invalid_session(self):
        # Step 2 with random session_id -> should return 404
        payload = {
            "session_id": "00000000-0000-0000-0000-000000000000",
            "budget": {
                "amount": 500000.0,
                "period": "weekly"
            }
        }
        res = requests.post(f"{BASE_URL}/api/v1/meal-plan", json=payload)
        self.assertEqual(res.status_code, 404)

    def test_05_meal_plan_infeasible_budget(self):
        # Step 1
        step1_payload = {
            "height_cm": 165.0,
            "weight_kg": 55.0,
            "age": 20,
            "gender": "female",
            "activity_level": "light",
            "goal": "maintain"
        }
        res1 = requests.post(f"{BASE_URL}/api/v1/nutrition/macros", json=step1_payload)
        self.assertEqual(res1.status_code, 200)
        session_id = res1.json()["session_id"]

        # Step 2 with extremely low budget (10,000 VND / month)
        step2_payload = {
            "session_id": session_id,
            "budget": {
                "amount": 10000.0,
                "period": "monthly"
            }
        }
        res2 = requests.post(f"{BASE_URL}/api/v1/meal-plan", json=step2_payload)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()

        self.assertFalse(data2["feasible"])
        self.assertEqual(len(data2["meals"]), 0)
        self.assertIsNotNone(data2["suggested_budget"])
        self.assertGreater(data2["suggested_budget"], 10000.0)
        self.assertIn("scenarios", data2)
        if data2.get("scenarios"):
            self.assertIn("standard_scenario", data2["scenarios"])



if __name__ == "__main__":
    unittest.main()
