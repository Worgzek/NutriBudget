/* Hiển thị kết quả meal-plan + thực đơn đã lưu (localStorage). */
(function () {
  const { $, fmt, money } = NB;
  const pLabel = p => (p === "monthly" ? "tháng" : "tuần");
  const KEY = "nutribudget_saved";
  let current = null; // { plan, budget, suggested } của thực đơn đang xem
  let currentId = null; // id nếu đang xem thực đơn đã lưu

  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { return []; } };
  const store = list => { try { localStorage.setItem(KEY, JSON.stringify(list)); return true; } catch (e) { return false; } };
  const refreshCount = () => { $("#saved-count").textContent = load().length; };
  const sum = (meals, k) => meals.reduce((s, m) => s + m.macros[k], 0);

  NB.handlePlan = (plan, ctx = {}) =>
    plan.feasible ? renderMenu(plan, ctx.budget || NB.state.budget, ctx.suggested, false) : renderInfeasible(plan);

  function applySuggest(sug, amount, period) {
    NB.setBudget(sug, period);
    $("#s-period").textContent = pLabel(period);
    $("#s-amount").textContent = money(sug);
    $("#s-have").textContent = money(amount);
    $("#s-need").textContent = money(Math.max(sug - amount, 0));
    $("#b-suggest").hidden = false;
    NB.show("budget");
  }

  function renderMenu(plan, budget, suggested, fromSaved) {
    current = { plan, budget, suggested };
    currentId = fromSaved || null;
    const { amount, period } = budget, meals = plan.meals || [];
    $("#menu-back").dataset.go = fromSaved ? "saved" : "budget";
    $("#menu-actions").hidden = $("#menu-saved-link").hidden = !!fromSaved;
    $("#menu-saved-label").hidden = $("#delete-saved").hidden = !fromSaved;
    if (fromSaved) $("#menu-saved-label").textContent = "📁 Đã lưu lúc " + new Date(fromSaved).toLocaleString("vi-VN");
    $("#save-menu").disabled = false; $("#save-label").textContent = "Lưu thực đơn";

    $("#m-kcal").textContent = fmt(sum(meals, "calories")) + " kcal";
    $("#m-p").textContent = fmt(sum(meals, "protein_g")) + "g";
    $("#m-f").textContent = fmt(sum(meals, "fat_g")) + "g";
    $("#m-c").textContent = fmt(sum(meals, "carb_g")) + "g";

    const total = plan.total_cost_estimate || 0, over = total > amount + 0.5;
    const pct = amount ? (total / amount) * 100 : 0;
    $("#c-period").textContent = pLabel(period);
    $("#c-total").textContent = money(total);
    $("#c-pct").textContent = pct.toFixed(1) + "%";
    $("#c-pct").classList.toggle("over", over);
    $("#c-bar").style.width = Math.min(pct, 100) + "%";
    $("#c-bar").classList.toggle("over", over);
    $("#c-budget").textContent = "Ngân sách: " + money(amount);
    $("#c-left").textContent = over ? "Vượt: " + money(total - amount) : "Còn lại: " + money(amount - total);
    $("#c-left").className = over ? "red" : "gr";

    // Cảnh báo thiếu tiền nhưng vẫn đề xuất thực đơn
    const w = $("#menu-warn"); w.hidden = !over;
    if (over) {
      const need = suggested || total;
      w.innerHTML = `<b>⚠️ Ngân sách chưa đủ</b><p>Với ${money(amount)}/${pLabel(period)} chưa đủ để đạt đủ dinh dưỡng mỗi ngày. Thực đơn dưới đây là đề xuất với mức tối thiểu khoảng <b>${money(need)}</b>/${pLabel(period)}, cần thêm <b>${money(Math.max(need - amount, 0))}</b>.</p>` +
        (fromSaved ? "" : '<button class="btn ghost" id="warn-adjust" type="button">Điều chỉnh ngân sách</button>');
      if (!fromSaved) $("#warn-adjust").onclick = () => applySuggest(need, amount, period);
    }

    $("#m-count").textContent = `${meals.length} bữa · Khoảng ${money(meals.reduce((s, m) => s + m.meal_cost, 0))}/ngày`;
    $("#meals").innerHTML = meals.map(m => `
      <div class="meal">
        <div class="meal-h">
          <div>
            <b>${m.meal_name}</b>${m.dish_name ? ` · <span class="dish-title" style="color: #2e7d32;">${m.dish_name}</span>` : ""}
          </div>
          <span>${money(m.meal_cost)}</span>
        </div>
        ${m.cooking_tip ? `<div class="cooking-tip" style="background: #f1f8e9; padding: 8px 12px; border-radius: 6px; font-size: 0.88rem; margin: 6px 0 10px; color: #33691e; line-height: 1.4;">💡 <b>Mẹo nấu 15p:</b> ${m.cooking_tip}</div>` : ""}
        <div class="rw h"><span>NGUYÊN LIỆU</span><span>LƯỢNG</span><span>CHI PHÍ</span></div>
        ${m.ingredients.map(i => `<div class="rw"><span>${i.name}</span><span>${fmt(i.amount_g)} g</span><span>${money(i.cost)}</span></div>`).join("")}
      </div>`).join("") + (plan.ai_advice ? `<div class="chef-advice-card" style="background: #fff8e1; border-left: 4px solid #ffb300; padding: 10px 14px; border-radius: 6px; margin-top: 14px; font-size: 0.9rem; color: #ff6f00;">👨‍🍳 <b>Lời khuyên từ Chef:</b> ${plan.ai_advice}</div>` : "");
    NB.show("menu");
  }


  // Chỉ còn dùng khi không có mức ngân sách gợi ý khả thi (hoặc gọi lại vẫn thất bại)
  function renderInfeasible(plan) {
    const { amount, period } = NB.state.budget, sug = plan.suggested_budget;
    $("#m-suggest").hidden = !sug;
    if (sug) {
      $("#m-msg").textContent = plan.message || `Với ${money(amount)}/${pLabel(period)}, chưa đủ nguyên liệu để đạt mục tiêu dinh dưỡng mỗi ngày của bạn.`;
      $("#m-period").textContent = pLabel(period);
      $("#m-amount").textContent = money(sug);
      $("#m-have").textContent = money(amount);
      $("#m-need").textContent = money(Math.max(sug - amount, 0));
    } else {
      $("#m-msg").textContent = plan.message || "Không tìm được thực đơn phù hợp.";
    }
    $("#m-adjust").textContent = sug ? "Điều chỉnh ngân sách" : "Quay lại";
    $("#m-adjust").onclick = () => { $("#modal").hidden = true; if (sug) applySuggest(sug, amount, period); };
    $("#modal").hidden = false;
    NB.show("budget");
  }

  /* ---- Lưu / xem lại thực đơn ---- */
  $("#save-menu").addEventListener("click", () => {
    if (!current) return;
    const list = load();
    list.unshift({ id: Date.now(), ...current });
    if (store(list)) {
      refreshCount();
      $("#save-menu").disabled = true; $("#save-label").textContent = "Đã lưu ✓";
    } else NB.toast("Không thể lưu thực đơn trên trình duyệt này");
  });

  const fmtDate = id => new Date(id).toLocaleString("vi-VN");
  const isOver = it => (it.plan.total_cost_estimate || 0) > it.budget.amount + 0.5;

  NB.hooks.saved = () => {
    const list = load();
    $("#saved-list").innerHTML = list.length ? list.map(it => `
      <div class="saved-item" data-id="${it.id}" data-act="view">
        <div class="si-main">
          <b>${fmtDate(it.id)}</b>
          <small>${fmt(sum(it.plan.meals, "calories"))} kcal/ngày · ${it.plan.meals.length} bữa · ${money(it.plan.total_cost_estimate)}/${pLabel(it.budget.period)}</small>
          ${isOver(it) ? '<span class="tag">Vượt ngân sách</span>' : ""}
        </div>
        <div class="acts"><button class="mini" data-act="view">Xem</button><button class="mini del" data-act="del">Xóa</button></div>
      </div>`).join("")
      : '<div class="empty"><p class="muted">Chưa có thực đơn nào được lưu.</p><button class="btn" data-go="profile">Tạo thực đơn mới</button></div>';
  };

  function removeSaved(id) {
    store(load().filter(x => x.id !== id));
    refreshCount();
    return true;
  }

  $("#saved-list").addEventListener("click", e => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const id = +b.closest(".saved-item").dataset.id, it = load().find(x => x.id === id);
    if (b.dataset.act === "view" && it) renderMenu(it.plan, it.budget, it.suggested, it.id);
    if (b.dataset.act === "del" && removeSaved(id)) NB.hooks.saved();
  });

  $("#delete-saved").addEventListener("click", () => {
    if (currentId && removeSaved(currentId)) NB.show("saved");
  });

  refreshCount();
})();