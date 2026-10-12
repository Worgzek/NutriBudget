/* ===== Phần dùng chung (state, điều hướng, gọi API, loader) - form1.js được nạp đầu tiên ===== */
/* Dùng chung: state, điều hướng, gọi API, loader. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const delay = ms => new Promise(r => setTimeout(r, ms));

  const NB = window.NB = {
    API: window.NB_API_URL || "http://localhost:8000",
    state: { profile: null, macros: null, budget: { amount: 0, period: "monthly" }, notes: "", plan: null },
    hooks: {},
    $, $$,
    fmt: n => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ","),
    money: n => NB.fmt(n) + "đ",

    show(id) {
      $$(".screen").forEach(s => s.classList.toggle("active", s.id === id));
      window.scrollTo(0, 0);
      if (NB.hooks[id]) NB.hooks[id]();
    },

    toast(msg) {
      const t = $("#toast"); t.textContent = msg; t.hidden = false;
      clearTimeout(NB._t); NB._t = setTimeout(() => (t.hidden = true), 3500);
    },

    async post(path, body, signal) {
      let res;
      try {
        res = await fetch(NB.API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
      } catch (e) {
        if (e.name === "AbortError") throw e;
        throw new Error("Không kết nối được máy chủ. Vui lòng thử lại.");
      }
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        let d = data && data.detail;
        if (Array.isArray(d)) d = d.map(x => x.msg).join("; ");
        throw new Error(d || `Lỗi máy chủ (${res.status})`);
      }
      return data;
    },

    /* Chạy animation vòng tròn + các bước trong lúc chờ `task` (Promise). */
    async loader(screen, task, minMs = 1800) {
      const C = 2 * Math.PI * 34;
      const ring = $(".ring-fg", screen), pct = $(".ring-pct", screen), steps = $$(".steps li", screen);
      let p = 0;
      const set = v => {
        p = v; ring.style.strokeDashoffset = C * (1 - v / 100);
        if (pct) pct.textContent = Math.round(v) + "%";
        const cur = steps.findIndex((_, i) => v < (i + 1) * 30);
        steps.forEach((li, i) => { li.classList.toggle("done", cur === -1 || i < cur); li.classList.toggle("cur", i === cur); });
      };
      set(0);
      const timer = setInterval(() => set(p + (90 - p) * 0.05), 100);
      try {
        const [result] = await Promise.all([task, delay(minMs)]);
        clearInterval(timer); set(100); await delay(300);
        return result;
      } finally { clearInterval(timer); }
    },
  };

  // Enter = sang bước tiếp theo: form thì submit, màn không có form thì bấm nút [data-enter]
  document.addEventListener("keydown", e => {
    if (e.key !== "Enter" || e.isComposing) return;
    const modal = $("#modal");
    if (modal && !modal.hidden) { e.preventDefault(); $("#m-adjust").click(); return; }
    const t = e.target;
    // nút/link tự xử lý Enter; ô nhập chữ trong <form> đã tự submit
    if (t.closest("button, a, textarea") || (t.tagName === "INPUT" && !["radio", "checkbox"].includes(t.type))) return;
    const screen = $(".screen.active");
    if (!screen) return;
    const form = $("form", screen);
    if (form) { e.preventDefault(); form.requestSubmit(); return; }
    const next = $("[data-enter]", screen);
    if (next) { e.preventDefault(); next.click(); }
  });

  document.addEventListener("click", e => {
    const b = e.target.closest("[data-go]");
    if (b) NB.show(b.dataset.go);
  });
})();

/* Form 1: hồ sơ -> mức vận động/mục tiêu -> gọi /nutrition/macros -> hiển thị macro. */
(function () {
  const { $, $$, fmt } = NB;
  const ACT = [
    ["sedentary", "Ít vận động", "Làm việc văn phòng, ít di chuyển"],
    ["light", "Vận động nhẹ", "Tập 1–3 buổi mỗi tuần"],
    ["moderate", "Vận động vừa phải", "Tập 3–5 buổi mỗi tuần"],
    ["heavy", "Vận động thường xuyên", "Tập 6–7 buổi/tuần hoặc lao động nặng"],
  ];
  const GOALS = [
    ["muscle_gain", "Tăng cơ", "Ưu tiên tăng khối lượng cơ"],
    ["weight_loss", "Giảm mỡ", "Giảm cân an toàn"],
    ["maintain", "Giữ cân", "Duy trì cân nặng hiện tại"],
  ];
  const GOAL_API = { muscle_gain: "muscle_gain", weight_loss: "weight_loss", maintain: "maintain" };

  const opts = (id, name, list, def) => {
    $(id).innerHTML = list.map(([v, t, d]) =>
      `<label class="opt"><input type="radio" name="${name}" value="${v}" ${v === def ? "checked" : ""}><span><b>${t}</b><small>${d}</small></span></label>`).join("");
  };
  opts("#activity-opts", "activity", ACT, "sedentary");
  opts("#goal-opts", "goal", GOALS, "muscle_gain");

  const field = k => $(`#profile-form [name="${k}"]`);
  const setErr = (k, m) => {
    $(`[data-err="${k}"]`).textContent = m || "";
    field(k).classList.toggle("invalid", !!m); // viền đỏ khi không hợp lệ
    return !m;
  };

  // Chỉ cho gõ số (không dùng ô number nên không có mũi tên/lăn chuột)
  const num = s => s.replace(",", ".");
  const RULES = {
    age: { label: "Tuổi", min: 13, max: 100, unit: "tuổi" },
    height: { label: "Chiều cao", min: 100, max: 250, unit: "cm" },
    weight: { label: "Cân nặng", min: 25, max: 300, unit: "kg" },
  };
  const check = (k, raw) => {
    const r = RULES[k], s = num(raw.trim());
    if (s === "") return `Vui lòng nhập ${r.label.toLowerCase()}`;
    const n = +s;
    if (isNaN(n) || n < r.min || n > r.max) return `${r.label} không hợp lệ (${r.min}–${r.max} ${r.unit})`;
    return "";
  };
  const sanitize = el => {
    let s = el.value;
    if (el.name === "age") s = s.replace(/\D/g, "").slice(0, 3);
    if (el.name === "height" || el.name === "weight") {
      s = s.replace(/[^\d.,]/g, "");
      const i = s.search(/[.,]/);
      if (i >= 0) s = s.slice(0, i + 1) + s.slice(i + 1).replace(/[.,]/g, "");
      s = s.slice(0, 6);
    }
    if (s !== el.value) el.value = s; // chỉ ghi khi có thay đổi
  };
  $("#profile-form").addEventListener("compositionend", e => sanitize(e.target));
  $("#profile-form").addEventListener("input", e => {
    const el = e.target;
    if (e.isComposing) return;
    sanitize(el);
    // đang hiện lỗi thì kiểm tra lại ngay khi người dùng sửa
    if (RULES[el.name] && $(`[data-err="${el.name}"]`).textContent) setErr(el.name, check(el.name, el.value));
    if (el.name === "name" && el.value.trim()) setErr("name", "");
  });
  // rời ô (đã nhập) thì báo luôn nếu sai
  $("#profile-form").addEventListener("focusout", e => {
    const k = e.target.name;
    if (RULES[k] && e.target.value.trim()) setErr(k, check(k, e.target.value));
  });

  /* ---- Submit hồ sơ ---- */
  $("#profile-form").addEventListener("submit", e => {
    e.preventDefault();
    const f = e.target, v = n => f.elements[n].value.trim();
    const ok = [
      setErr("name", v("name") ? "" : "Vui lòng nhập họ và tên"),
      setErr("age", check("age", v("age"))),
      setErr("height", check("height", v("height"))),
      setErr("weight", check("weight", v("weight"))),
    ].every(Boolean);
    if (!ok) return;
    NB.state.profile = { name: v("name"), age: +v("age"), gender: f.elements.gender.value, height_cm: +num(v("height")), weight_kg: +num(v("weight")) };
    NB.show("plan");
  });

  /* ---- Submit kế hoạch -> gọi API ---- */
  $("#plan-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, p = NB.state.profile;
    const goalUi = f.elements.goal.value;
    const body = {
      height_cm: p.height_cm, weight_kg: p.weight_kg, age: p.age, gender: p.gender,
      activity_level: f.elements.activity.value, goal: GOAL_API[goalUi],
    };
    $("#calc-goal").textContent = "Ưu tiên mục tiêu " + GOALS.find(g => g[0] === goalUi)[1].toLowerCase();
    NB.show("calc");
    try {
      NB.state.macros = await NB.loader($("#calc"), NB.post("/api/v1/nutrition/macros", body));
      renderMacros();
      NB.show("result");
    } catch (err) {
      NB.toast(err.message); NB.show("plan");
    }
  });

  function renderMacros() {
    const m = NB.state.macros, p = NB.state.profile;
    $("#r-kcal").textContent = fmt(m.calories);
    $("#r-protein").textContent = fmt(m.protein_g) + "g";
    $("#r-fat").textContent = fmt(m.fat_g) + "g";
    $("#r-carb").textContent = fmt(m.carb_g) + "g";
    $("#r-explain").textContent = m.explanation || "";
    const w = $("#r-warn"), list = m.warning || [];
    w.hidden = !list.length;
    w.innerHTML = list.length ? "<b>⚠️ Lưu ý</b>" + list.map(t => `<p>${t}</p>`).join("") : "";
    const bmi = p.weight_kg / Math.pow(p.height_cm / 100, 2);
    const cat = bmi < 18.5 ? "Thiếu cân" : bmi < 25 ? "Nằm trong phạm vi cân đối" : bmi < 30 ? "Thừa cân" : "Béo phì";
    $("#r-bmi").textContent = `CHỈ SỐ BMI ${bmi.toFixed(1)} · ${cat}`;
    // Tóm tắt "Nhu cầu mỗi ngày" ở màn ngân sách
    $("#b-kcal").textContent = fmt(m.calories);
    $("#b-p").textContent = fmt(m.protein_g) + "g";
    $("#b-f").textContent = fmt(m.fat_g) + "g";
    $("#b-c").textContent = fmt(m.carb_g) + "g";
  }
})();