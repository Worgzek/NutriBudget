/* Form 2: ngân sách (+ ghi chú dị ứng/sở thích) -> gọi /meal-plan. */
(function () {
  // Thiếu tiền vẫn hiện thực đơn đề xuất (gọi API lần 2). Tắt theo mặc định, chỉ bật khi lead đồng ý.
  const SHOW_MENU_WHEN_SHORT = false;
  const { $, $$, fmt } = NB;
  const inp = $("#b-amount");
  const days = () => (NB.state.budget.period === "monthly" ? 30 : 7);
  const amount = () => +inp.value.replace(/\D/g, "") || 0;

  function update() {
    const a = amount(), monthly = NB.state.budget.period === "monthly";
    NB.state.budget.amount = a;
    // Có số tiền là hiện ngay; chưa nhập thì hiện "—"
    $("#b-daily").textContent = a ? fmt(a / days()) + " VND/ngày" : "—";
    $("#b-other-l").textContent = monthly ? "Theo tuần" : "Theo tháng";
    $("#b-other").textContent = a ? fmt(monthly ? (a / 30) * 7 : (a / 7) * 30) + (monthly ? " VND/tuần" : " VND/tháng") : "—";
  }

  // Vừa gõ vừa tự thêm dấu phẩy (900,000). Giữ nguyên vị trí con trỏ và không đụng vào
  // giá trị khi bộ gõ tiếng Việt đang soạn chữ (isComposing) để không bị chèn/mất số.
  const format = () => {
    const raw = inp.value, pos = inp.selectionStart ?? raw.length;
    const before = raw.slice(0, pos).replace(/\D/g, "").length;
    const f = fmt(+raw.replace(/\D/g, "").slice(0, 12) || 0);
    const next = raw.replace(/\D/g, "") === "" ? "" : f;
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
    NB.state.budget.period = t.dataset.period;
    update();
  }));

  // Cho result.js dùng: đặt lại ngân sách (vd. áp dụng mức gợi ý)
  NB.setBudget = (amt, period) => {
    NB.state.budget.period = period;
    $$(".tab").forEach(x => x.classList.toggle("active", x.dataset.period === period));
    inp.value = amt ? fmt(amt) : "";
    update();
  };

  $("#budget-form").addEventListener("submit", async e => {
    e.preventDefault();
    if (amount() <= 0) { $("#b-err").textContent = "Vui lòng nhập ngân sách lớn hơn 0"; return; }
    const m = NB.state.macros;
    if (!m || !NB.state.session_id) {
      NB.toast("Vui lòng hoàn thành bước tính dinh dưỡng trước");
      NB.show("profile");
      return;
    }
    NB.state.notes = $("#b-notes").value.trim();
    const { amount: amt, period } = NB.state.budget;
    const body = {
      session_id: NB.state.session_id,
      budget: { amount: amt, period },
      notes: NB.state.notes || null,
    };
    $("#o-budget").textContent = `Ngân sách: ${NB.money(amt)} / ${period === "monthly" ? "tháng" : "tuần"}`;
    const ctrl = new AbortController();
    $("#cancel-opt").onclick = () => { ctrl.abort(); NB.show("budget"); };
    NB.show("optimizing");
    // Thiếu tiền: backend trả infeasible + suggested_budget -> gọi lại với mức tối thiểu để vẫn có thực đơn đề xuất
    const fetchPlan = async () => {
      let plan = await NB.post("/api/v1/meal-plan", body, ctrl.signal), suggested = null;
      if (SHOW_MENU_WHEN_SHORT && !plan.feasible && plan.suggested_budget) {
        const retry = { ...body, budget: { amount: Math.ceil(plan.suggested_budget * 1.02), period } };
        try {
          const p2 = await NB.post("/api/v1/meal-plan", retry, ctrl.signal);
          if (p2.feasible) { suggested = plan.suggested_budget; plan = p2; }
        } catch (e) { if (e.name === "AbortError") throw e; }
      }
      return { plan, suggested };
    };
    try {
      const { plan, suggested } = await NB.loader($("#optimizing"), fetchPlan());
      NB.state.plan = plan;
      NB.handlePlan(plan, { budget: { amount: amt, period }, suggested });
    } catch (err) {
      if (err.name === "AbortError") return;
      NB.toast(err.message); NB.show("budget");
    }
  });
})();