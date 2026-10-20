-- 1. Foods - input cho optimize_meal_plan()
CREATE TABLE IF NOT EXISTS foods (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL
        CHECK (category IN ('protein', 'carb', 'vegetable', 'fruit', 'dairy', 'fat', 'other')),
    price_per_unit DECIMAL(10,2) NOT NULL CHECK (price_per_unit >= 0),
    unit VARCHAR(50) NOT NULL DEFAULT '100g',
    calories DECIMAL(6,2) NOT NULL CHECK (calories >= 0),
    protein DECIMAL(6,2) NOT NULL CHECK (protein >= 0),
    carbs DECIMAL(6,2) NOT NULL CHECK (carbs >= 0),
    fat DECIMAL(6,2) NOT NULL CHECK (fat >= 0),
    allergen_tags TEXT[] NOT NULL DEFAULT '{}',
    meal_types TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexing
CREATE INDEX IF NOT EXISTS idx_foods_allergen_tags ON foods USING GIN (allergen_tags);
CREATE INDEX IF NOT EXISTS idx_foods_category ON foods (category);

-- 2. Request logs
CREATE TABLE IF NOT EXISTS request_logs (
    id SERIAL PRIMARY KEY,
    endpoint VARCHAR(100) NOT NULL,       -- 'nutrition/macros' hoặc 'meal-plan'
    request_payload JSONB NOT NULL,
    response_payload JSONB NOT NULL,
    feasible BOOLEAN,                      -- null cho endpoint macros, true/false cho meal-plan
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_endpoint ON request_logs (endpoint);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs (created_at);