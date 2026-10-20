# NutriBudget

NutriBudget is a prototype AI Agent for affordable, personalized meal planning. It fits the **Healthcare & Well-being** theme of the “AI Agents – Agent of Change” challenge. The prototype demonstrates a two-step flow: calculate nutrition targets, then plan meals against a user budget.

> Educational prototype only. It is not a medical or clinical nutrition service.

## What it demonstrates

- An ADK Supervisor routes profile requests to a Nutrition Agent and budget requests to a Meal Planning Agent.
- Python computes nutrition targets; the food catalog and PuLP solver perform filtering and cost optimization.
- Users explicitly select allergy groups (including soy) and can separately enter preference notes.
- When the budget is too low, original targets stay unchanged. The interface presents an estimated minimum budget and waits for the user to retry or edit constraints.
- The interface displays verified completed tool actions returned by the backend, not fabricated progress or hidden reasoning.
- Transient Gemini failures use bounded retries and configured model fallback; Chef suggestions fall back to solver ingredients when unavailable.

## User flow

1. Enter profile and goal. The prototype accepts users aged 13–100; users under 18 receive an additional caution with the result.
2. Review calculated daily calories and macros.
3. Enter a weekly/monthly budget, select exclusions and add optional food preferences.
4. Review the feasible meal plan or choose how to respond to an infeasible budget.

## Stack

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend | HTML, CSS, JavaScript | Two-step form, verified action trace and results |
| API | FastAPI, Pydantic | Request validation and session-based routes |
| Agent | Google ADK, Gemini API | Request routing and grounded explanation |
| Nutrition | Python | Deterministic nutrition calculation |
| Optimization | PuLP | Meal-plan feasibility and cost optimization |
| Data | PostgreSQL, SQL seed data | Food nutrition, prices and allergen tags |
| Runtime | Docker Compose | Local backend and database |

## Run locally

1. Copy `.env.example` to `.env`, then set database credentials and `GOOGLE_API_KEY`.
2. Optionally configure the Gemini model order with `GEMINI_MODEL` and `GEMINI_FALLBACK_MODELS`.
3. Run `docker compose up --build`.
4. Open [http://localhost:8000](http://localhost:8000); API docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Frontend development can also serve the `frontend/` directory separately; set `window.NB_API_URL` to the backend URL when needed.

## Key files

- `backend/app/main.py` — API routes and request/result checks
- `backend/app/agents/setup.py` — ADK workflow, retries and model fallback
- `backend/app/agents/tools.py` — tool implementations and trace events
- `backend/app/planner/optimizer.py` — PuLP meal-plan solver
- `database/seed.sql` — food catalog seed data
- `frontend/` — prototype UI
- `docs/AGENT_FLOW.md` — detailed flow and contracts

See `docs/` for the project concept, stack and team task documents. Never commit `.env` or API keys.
