const bridge = window.AstrBotPluginPage;

const status = document.getElementById("status");
const tableBody = document.querySelector("#membersTable tbody");
const formWrap = document.getElementById("formWrap");
const searchInput = document.getElementById("searchInput");

let editingQQ = null; // 非 null 表示正在编辑已有成员

function setStatus(msg) {
  status.textContent = msg;
}

function renderRows(members) {
  tableBody.innerHTML = "";
  if (!members || members.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = "暂无数据";
    td.style.color = "var(--muted)";
    tr.appendChild(td);
    tableBody.appendChild(tr);
    return;
  }
  for (const m of members) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(m.qq)}</td>
      <td>${esc(m.nickname)}</td>
      <td>${esc(m.card_name)}</td>
      <td>${esc(m.occupation)}</td>
      <td>${esc(m.location)}</td>
      <td>
        <button data-action="edit" data-qq="${esc(m.qq)}" class="secondary">编辑</button>
        <button data-action="del" data-qq="${esc(m.qq)}" class="danger">删除</button>
      </td>
    `;
    tableBody.appendChild(tr);
  }
}

function esc(v) {
  if (v === null || v === undefined) return "";
  return String(v).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function showForm(member) {
  editingQQ = member ? member.qq : null;
  document.getElementById("f_qq").value = member ? member.qq : "";
  document.getElementById("f_qq").disabled = member != null;
  document.getElementById("f_nickname").value = member?.nickname || "";
  document.getElementById("f_card_name").value = member?.card_name || "";
  document.getElementById("f_occupation").value = member?.occupation || "";
  document.getElementById("f_location").value = member?.location || "";
  document.getElementById("f_hobby").value = member?.hobby || "";
  document.getElementById("f_remark").value = member?.remark || "";
  formWrap.style.display = "block";
}

function hideForm() {
  formWrap.style.display = "none";
  editingQQ = null;
  document.getElementById("f_qq").disabled = false;
}

async function loadAll() {
  try {
    const data = await bridge.apiGet("members", { limit: 200 });
    renderRows(data.members || []);
    setStatus(`共 ${(data.members || []).length} 条`);
  } catch (e) {
    setStatus("加载失败：" + e.message);
  }
}

async function doSave() {
  const payload = {
    qq: Number(document.getElementById("f_qq").value),
    nickname: document.getElementById("f_nickname").value,
    card_name: document.getElementById("f_card_name").value,
    occupation: document.getElementById("f_occupation").value,
    location: document.getElementById("f_location").value,
    hobby: document.getElementById("f_hobby").value,
    remark: document.getElementById("f_remark").value,
  };
  if (!payload.qq) {
    setStatus("请填写 QQ 号");
    return;
  }
  try {
    await bridge.apiPost("members/save", payload);
    setStatus("已保存");
    hideForm();
    await loadAll();
  } catch (e) {
    setStatus("保存失败：" + e.message);
  }
}

async function doDelete(qq) {
  if (!confirm(`确定删除 QQ ${qq} 的档案吗？`)) return;
  try {
    await bridge.apiPost("members/delete", { qq: Number(qq) });
    setStatus("已删除");
    await loadAll();
  } catch (e) {
    setStatus("删除失败：" + e.message);
  }
}

tableBody.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const qq = btn.dataset.qq;
  if (btn.dataset.action === "edit") {
    try {
      const data = await bridge.apiGet("members/get", { qq: qq });
      showForm(data.member);
    } catch (err) {
      setStatus("读取失败：" + err.message);
    }
  } else if (btn.dataset.action === "del") {
    await doDelete(qq);
  }
});

document.getElementById("searchBtn").addEventListener("click", async () => {
  const kw = searchInput.value.trim();
  if (!kw) { await loadAll(); return; }
  try {
    const data = await bridge.apiGet("members/search", { keyword: kw });
    renderRows(data.members || []);
    setStatus(`匹配 ${(data.members || []).length} 条`);
  } catch (e) {
    setStatus("搜索失败：" + e.message);
  }
});

document.getElementById("resetBtn").addEventListener("click", () => {
  searchInput.value = "";
  loadAll();
});

document.getElementById("newBtn").addEventListener("click", () => showForm(null));
document.getElementById("saveBtn").addEventListener("click", doSave);
document.getElementById("cancelBtn").addEventListener("click", hideForm);

await bridge.ready();
await loadAll();
