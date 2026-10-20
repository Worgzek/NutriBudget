/* Ngân sách + lựa chọn dị ứng có cấu trúc -> gọi /meal-plan. */
(function () {
  const { $, $$, fmt } = NB;
  const inp = $("#b-amount");
  const days = () => NB.state.budget.period === "monthly" ? 30 : 7;
  const amount = () => +inp.value.replace(/\D/g, "") || 0;
  const selectedAllergens = () => $$("input[name='allergens']:checked").map(el => el.value);
  const ALLERGY_CUES = /dị ứng|allergy|không dung nạp|không ăn được|phản ứng với|allergic/i;
  const ALLERGEN_TERMS = {
    seafood: /hải sản|cá|tôm|cua|mực|seafood|fish|shrimp|crab/i,
    dairy: /sữa|phô mai|bơ sữa|dairy|milk|cheese/i,
    peanut: /đậu phộng|lạc|peanut/i,
    gluten: /gluten|lúa mì|wheat|lúa mạch|barley/i,
    egg: /trứng|egg/i,
    soy: /đậu nành|đậu tương|đậu phụ|đậu hũ|soy|tofu/i,
    sesame: /mè|vừng|sesame/i,
  };
  function validateAllergyNotes() {
    const notes = $("#b-notes").value.trim();
    const mentioned = Object.entries(ALLERGEN_TERMS).filter(([, re]) => re.test(notes)).map(([key]) => key);
    const chosen = selectedAllergens();
    const ambiguous = ALLERGY_CUES.test(notes) && (!mentioned.length || mentioned.some(key => !chosen.includes(key)));
    $("#allergen-error").textContent = ambiguous
      ? "Ghi chú có nhắc đến dị ứng/không dung nạp. Hãy chọn đúng nhóm ở trên hoặc sửa ghi chú để tránh hiểu nhầm."
      : "";
    return !ambiguous;
  }
  function update() {
    const a = amount(), monthly = NB.state.budget.period === "monthly";
    NB.state.budget.amount = a;
    $("#b-daily").textContent = a ? fmt(a / days()) + " VND/ngày" : "—";
    $("#b-other-l").textContent = monthly ? "Theo tuần" : "Theo tháng";
    $("#b-other").textContent = a ? fmt(monthly ? (a / 30) * 7 : (a / 7) * 30) + (monthly ? " VND/tuần" : " VND/tháng") : "—";
  }
  const format = () => {
    const raw = inp.value, pos = inp.selectionStart ?? raw.length;
    const before = raw.slice(0, pos).replace(/\D/g, "").length;
    const digits = raw.replace(/\D/g, "").slice(0, 12);
    const next = digits ? fmt(+digits) : "";
    if (next !== raw) {
      inp.value = next;
      let p = 0, c = 0;
      while (p < next.length && c < before) { if (/\d/.test(next[p])) c++; p++; }
      inp.setSelectionRange(p, p);
    }
    $("#b-err").textContent = "";
    update();
  };
  inp.addEventListener("input", e => { if (!e.isComposing) format(); });
  inp.addEventListener("compositionend", format);
  $$(".tab").forEach(t => t.addEventListener("click", () => {
    $$(".tab").forEach(x => x.classList.toggle("active", x === t));
    NB.state.budget.period = t.dataset.period; update();
  }));
  NB.setBudget = (amt, period) => {
    NB.state.budget.period = period;
    $$(".tab").forEach(x => x.classList.toggle("active", x.dataset.period === period));
    inp.value = amt ? fmt(amt) : ""; update();
  };

  async function generateMealPlan(amt, period, rotationExclusions = []) {
    const m = NB.state.macros;
    if (!m || !NB.state.session_id) throw new Error("Vui lòng hoàn thành bước tính dinh dưỡng trước.");
    if (!validateAllergyNotes()) { NB.show("budget"); return; }
    NB.setBudget(amt, period);
    NB.state.notes = $("#b-notes").value.trim();
    NB.state.allergens = selectedAllergens();
    const body = {
      session_id: NB.state.session_id,
      budget: { amount: amt, period },
      allergens: NB.state.allergens,
      notes: NB.state.notes || null,
      rotation_exclusions: rotationExclusions,
    };
    $("#o-budget").textContent = "Ngân sách: " + NB.money(amt) + " / " + (period === "monthly" ? "tháng" : "tuần");
    const ctrl = new AbortController();
    $("#cancel-opt").onclick = () => { ctrl.abort(); NB.show("budget"); };
    NB.show("optimizing");
    try {
      const plan = await NB.loader($("#optimizing"), NB.post("/api/v1/meal-plan", body, ctrl.signal));
      NB.state.plan = plan;
      NB.handlePlan(plan, { budget: { amount: amt, period } });
    } catch (err) {
      if (err.name === "AbortError") return;
      NB.toast(err.message); NB.show("budget");
    }
  }
  NB.generateMealPlan = generateMealPlan;
  $("#budget-form").addEventListener("submit", async e => {
    e.preventDefault();
    if (amount() <= 0) { $("#b-err").textContent = "Vui lòng nhập ngân sách lớn hơn 0"; return; }
    if (!validateAllergyNotes()) return;
    await generateMealPlan(amount(), NB.state.budget.period);
  });
  $("#b-notes").addEventListener("input", validateAllergyNotes);
  $$("input[name='allergens']").forEach(el => el.addEventListener("change", validateAllergyNotes));
})();
