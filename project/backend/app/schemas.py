from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

ActivityLevel = Literal["sedentary", "light", "moderate", "heavy"]
Goal = Literal["weight_loss", "maintain", "muscle_gain"]
Gender = Literal["male", "female"]

class NutritionRequest(BaseModel):
    height_cm: float = Field(..., gt=0, le=250)
    weight_kg: float = Field(..., gt=0, le=300)
    age: int = Field(..., gt=0, le=120)
    gender: Gender
    activity_level: ActivityLevel
    goal: Goal
    notes: Optional[str] = Field(None, max_length=200)

class NutritionResponse(BaseModel):
    session_id: str
    calories: float
    protein_g: float
    fat_g: float
    carb_g: float
    explanation: str
    warning: Optional[list[str]] = None

class MacroTargets(BaseModel):
    calories: float
    protein_g: float
    fat_g: float
    carb_g: float

BudgetPeriod = Literal["weekly", "monthly"]

class Budget(BaseModel):
    amount: float = Field(..., ge=0)
    period: BudgetPeriod

class MealPlanRequest(BaseModel):
    session_id: str
    budget: Budget
    notes: Optional[str] = Field(None, max_length=200)

class Ingredient(BaseModel):
    name: str
    amount_g: float = Field(..., ge=0)
    cost: float = Field(..., ge=0)

class Meal(BaseModel):
    meal_name: str
    dish_name: Optional[str] = Field(None, description="Tên món ăn thực tế gợi ý từ Chef Agent")
    cooking_tip: Optional[str] = Field(None, description="Mẹo chế biến 10-15p cho sinh viên")
    ingredients: List[Ingredient]
    macros: MacroTargets
    meal_cost: float = Field(..., ge=0)

class MealPlanResponse(BaseModel):
    feasible: bool
    meals: List[Meal] = Field(default_factory=list)
    total_cost_estimate: Optional[float] = None
    message: Optional[str] = None
    suggested_budget: Optional[float] = None
    scenarios: Optional[dict] = Field(None, description="Kịch bản tự thương lượng/cứu vãn khi thiếu ngân sách")
    ai_advice: Optional[str] = Field(None, description="Lời khuyên tổng thể từ Chef Agent & Dinh dưỡng")


FoodCategory = Literal["protein", "carb", "vegetable", "fruit", "dairy", "fat", "other"]

class FoodCreate(BaseModel):
    name: str
    category: FoodCategory
    price_per_unit: float = Field(..., ge=0)
    unit: str = "100g"
    calories: float = Field(..., ge=0)
    protein: float = Field(..., ge=0)
    carbs: float = Field(..., ge=0)
    fat: float = Field(..., ge=0)
    allergen_tags: List[str] = Field(default_factory=list)

class FoodResponse(FoodCreate):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

class Allergen(BaseModel):
    key: str
    label: str

class RequestLogCreate(BaseModel):
    endpoint: Literal["nutrition/macros", "meal-plan"]
    request_payload: dict
    response_payload: dict
    feasible: Optional[bool] = None