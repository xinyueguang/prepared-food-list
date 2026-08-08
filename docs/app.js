const CONFIG = {
  dataUrl: "./data/prepared-foods.json?v=20260808-clean",
  githubOwner: "xinyueguang",
  githubRepo: "prepared-food-list",
  submissionEndpoint: "",
};

const state = {
  payload: null,
  items: [],
  filtered: [],
};

const elements = {
  total: document.querySelector("#totalCount"),
  evidence: document.querySelector("#evidenceCount"),
  notes: document.querySelector("#noteCount"),
  related: document.querySelector("#relatedCount"),
  resultCount: document.querySelector("#resultCount"),
  dataMeta: document.querySelector("#dataMeta"),
  rows: document.querySelector("#itemsBody"),
  empty: document.querySelector("#emptyState"),
  search: document.querySelector("#searchInput"),
  statusFilter: document.querySelector("#statusFilter"),
  relatedFilter: document.querySelector("#relatedFilter"),
  evidenceFilter: document.querySelector("#evidenceFilter"),
  copyVisible: document.querySelector("#copyVisible"),
  openSubmit: document.querySelector("#openSubmit"),
  closeSubmit: document.querySelector("#closeSubmit"),
  dialog: document.querySelector("#submitDialog"),
  submissionForm: document.querySelector("#submissionForm"),
  copySubmission: document.querySelector("#copySubmission"),
  submissionMode: document.querySelector("#submissionMode"),
  toast: document.querySelector("#toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function normalize(value) {
  return String(value ?? "").trim().toLowerCase();
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("toast--show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    elements.toast.classList.remove("toast--show");
  }, 2400);
}

function statusBadgeClass(status) {
  if (status === "待补充证据") return "badge badge--empty";
  if (status === "有备注") return "badge badge--warn";
  return "badge";
}

function renderTags(tags) {
  if (!tags || tags.length === 0) return "";
  return `<div class="tag-list">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function renderEvidence(item) {
  if (!item.evidenceUrl) return `<span class="muted">待补充</span>`;
  const label = item.evidenceHost || "外部链接";
  return `<a class="evidence-link" href="${escapeHtml(item.evidenceUrl)}" target="_blank" rel="noreferrer"><span>${escapeHtml(label)}</span></a>`;
}

function renderImagePanel(label, image) {
  if (!image) {
    return `
      <div class="compare-panel compare-panel--empty">
        <div class="compare-panel__head">${escapeHtml(label)}</div>
        <div class="compare-empty">暂无图片</div>
      </div>
    `;
  }

  return `
    <a class="compare-panel" href="${escapeHtml(image.url)}" target="_blank" rel="noreferrer" title="打开${escapeHtml(label)}">
      <div class="compare-panel__head">${escapeHtml(label)}</div>
      <div class="compare-frame">
        <img src="${escapeHtml(image.url)}" alt="${escapeHtml(label)}">
      </div>
    </a>
  `;
}

function renderImageComparison(item) {
  const projectImage = item.projectImages?.[0] || item.images?.find((image) => image.label?.includes("金海豚"));
  const evidenceImage = item.evidenceImages?.[0] || item.images?.find((image) => image.label?.includes("证据"));
  return `
    <div class="compare-grid">
      ${renderImagePanel("金海豚项目图片", projectImage)}
      ${renderImagePanel("证据图片", evidenceImage)}
    </div>
  `;
}

function fillFilters() {
  const statuses = uniqueSorted(state.items.map((item) => item.status));
  elements.statusFilter.innerHTML = `<option value="">全部状态</option>${statuses
    .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(status)}</option>`)
    .join("")}`;

  const related = uniqueSorted(state.items.map((item) => item.related));
  elements.relatedFilter.innerHTML = `<option value="">全部关联对象</option>${related
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("")}`;
}

function renderStats() {
  const summary = state.payload?.summary || {};
  elements.total.textContent = summary.total ?? state.items.length;
  elements.evidence.textContent = summary.withEvidence ?? state.items.filter((item) => item.evidenceUrl).length;
  elements.notes.textContent = summary.withNotes ?? state.items.filter((item) => item.note).length;
  elements.related.textContent = summary.relatedCount ?? uniqueSorted(state.items.map((item) => item.related)).length;

  const generated = formatDateTime(state.payload?.generatedAt);
  elements.dataMeta.textContent = generated
    ? `数据来源：${state.payload.sourceFile || "预制菜.xlsx"} · 更新于 ${generated}`
    : `数据来源：${state.payload?.sourceFile || "预制菜.xlsx"}`;
}

function renderRows() {
  elements.resultCount.textContent = `${state.filtered.length} 条`;
  elements.empty.hidden = state.filtered.length > 0;
  elements.rows.innerHTML = state.filtered
    .map(
      (item, index) => `
        <tr class="case-row ${index % 2 === 0 ? "case-row--red" : "case-row--black"}">
          <td class="col-index">${index + 1}</td>
          <td class="image-compare-cell">
            ${renderImageComparison(item)}
          </td>
          <td class="compact-info-cell">
            <span class="item-name">${escapeHtml(item.name)}</span>
            <span class="item-id">${escapeHtml(item.id)}</span>
            <div class="status-line"><span class="${statusBadgeClass(item.status)}">${escapeHtml(item.status)}</span></div>
            <div class="info-block">
              <span class="info-label">开发者</span>
              <span>${item.related ? escapeHtml(item.related) : `<span class="muted">未填写</span>`}</span>
            </div>
            ${renderTags(item.tags)}
          </td>
          <td class="note-link-cell">
            <div class="note-cell">${item.note ? escapeHtml(item.note) : `<span class="muted">无备注</span>`}</div>
            <div class="link-stack">${renderEvidence(item)}</div>
          </td>
        </tr>
      `
    )
    .join("");
}

function applyFilters() {
  const keyword = normalize(elements.search.value);
  const status = elements.statusFilter.value;
  const related = elements.relatedFilter.value;
  const evidence = elements.evidenceFilter.value;

  state.filtered = state.items.filter((item) => {
    const haystack = normalize(
      [item.name, item.related, item.status, item.note, item.evidenceUrl, ...(item.tags || [])].join(" ")
    );
    const matchesKeyword = !keyword || haystack.includes(keyword);
    const matchesStatus = !status || item.status === status;
    const matchesRelated = !related || item.related === related;
    const matchesEvidence =
      !evidence || (evidence === "with" ? Boolean(item.evidenceUrl) : !item.evidenceUrl);
    return matchesKeyword && matchesStatus && matchesRelated && matchesEvidence;
  });

  renderRows();
}

function visibleRowsAsText() {
  return state.filtered
    .map((item, index) => {
      const lines = [
        `${index + 1}. ${item.name}`,
        item.related ? `关联对象：${item.related}` : "",
        `状态：${item.status}`,
        item.note ? `备注：${item.note}` : "",
        item.evidenceUrl ? `证据链接：${item.evidenceUrl}` : "",
      ].filter(Boolean);
      return lines.join("\n");
    })
    .join("\n\n");
}

async function copyText(text, message) {
  await navigator.clipboard.writeText(text);
  showToast(message);
}

function fileSummary(input) {
  const file = input.files?.[0];
  if (!file) return null;
  return {
    name: file.name,
    size: file.size,
    type: file.type,
  };
}

function collectSubmission() {
  const projectImageInput = document.querySelector("#submissionProjectImage");
  const evidenceImageInput = document.querySelector("#submissionEvidenceImage");
  return {
    name: document.querySelector("#submissionName").value.trim(),
    projectImage: fileSummary(projectImageInput),
    evidenceImage: fileSummary(evidenceImageInput),
    note: document.querySelector("#submissionNote").value.trim(),
    linkUrl: document.querySelector("#submissionLink").value.trim(),
    developer: document.querySelector("#submissionDeveloper").value.trim(),
    submittedAt: new Date().toISOString(),
  };
}

function submissionMarkdown(payload) {
  return [
    "### 名称",
    payload.name || "未填写",
    "",
    "### 金海豚项目图片",
    payload.projectImage?.name || "未上传",
    "",
    "### 证据图片",
    payload.evidenceImage?.name || "未上传",
    "",
    "### 备注",
    payload.note || "未填写",
    "",
    "### 跳转链接",
    payload.linkUrl || "未填写",
    "",
    "### 开发者（曾用名）",
    payload.developer || "未填写",
    "",
    "---",
    "来自网站投稿入口。合并到公开数据前请人工核验；如使用 GitHub Issues，请在本 issue 中附上两张图片原文件。",
  ].join("\n");
}

function githubIssueUrl(payload) {
  const title = `投稿：${payload.name || "新条目"}`;
  const body = submissionMarkdown(payload);
  const params = new URLSearchParams({
    title,
    body,
    labels: "投稿,待核验",
  });
  return `https://github.com/${CONFIG.githubOwner}/${CONFIG.githubRepo}/issues/new?${params.toString()}`;
}

async function sendSubmission(payload) {
  if (CONFIG.submissionEndpoint) {
    const formData = new FormData(elements.submissionForm);
    formData.set("submittedAt", payload.submittedAt);
    const response = await fetch(CONFIG.submissionEndpoint, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) throw new Error("投稿接口返回失败");
    showToast("投稿已发送。");
    elements.dialog.close();
    elements.submissionForm.reset();
    return;
  }

  window.open(githubIssueUrl(payload), "_blank", "noopener,noreferrer");
  elements.dialog.close();
}

async function loadData() {
  try {
    const response = await fetch(CONFIG.dataUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.payload = await response.json();
    state.items = Array.isArray(state.payload.items) ? state.payload.items : [];
    state.filtered = [...state.items];
    fillFilters();
    renderStats();
    applyFilters();
  } catch (error) {
    elements.dataMeta.textContent = `数据载入失败：${error.message}`;
    elements.empty.hidden = false;
    elements.empty.textContent = "数据载入失败";
  }
}

elements.search.addEventListener("input", applyFilters);
elements.statusFilter.addEventListener("change", applyFilters);
elements.relatedFilter.addEventListener("change", applyFilters);
elements.evidenceFilter.addEventListener("change", applyFilters);
elements.copyVisible.addEventListener("click", () => {
  if (state.filtered.length === 0) return;
  copyText(visibleRowsAsText(), `已复制 ${state.filtered.length} 条结果。`);
});
elements.openSubmit.addEventListener("click", () => elements.dialog.showModal());
elements.closeSubmit.addEventListener("click", () => elements.dialog.close());
elements.copySubmission.addEventListener("click", () => {
  const payload = collectSubmission();
  copyText(JSON.stringify(payload, null, 2), "投稿 JSON 已复制。");
});
elements.submissionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = collectSubmission();
  if (!payload.name || !payload.projectImage || !payload.evidenceImage) {
    showToast("请填写名称，并上传两张必填图片。");
    return;
  }
  try {
    await sendSubmission(payload);
  } catch (error) {
    showToast(error.message);
  }
});

if (CONFIG.submissionEndpoint) {
  elements.submissionMode.textContent = "当前投稿会发送到配置的接口，合并到数据前需要人工核验。";
}

loadData();
