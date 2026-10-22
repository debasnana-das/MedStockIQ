(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const DATE_FIELDS = new Set(["expiry_date", "manufacturing_date", "transaction_date", "document_date"]);
  const QUANTITY_FIELDS = new Set(["quantity", "free_quantity", "current_quantity", "quantity_on_hand", "opening_stock"]);
  const DATE_FORMATS = ["MM/YY", "MM/YYYY", "DD/MM/YY", "DD/MM/YYYY", "YYYY-MM-DD", "DD-MM-YYYY", "DD.MM.YYYY", "YYYY/MM/DD"];
  const MOVEMENT_TYPES = [
    ["opening_balance", "Opening balance"], ["purchase_receipt", "Purchase receipt"],
    ["retailer_dispatch", "Retailer dispatch"], ["retail_sale", "Retail sale"],
    ["customer_return", "Customer return"], ["supplier_return", "Supplier return"],
    ["stock_adjustment", "Stock adjustment"], ["damaged_writeoff", "Damaged write-off"],
    ["expiry_writeoff", "Expiry write-off"]
  ];
  const state = {
    token: null, user: null, organizations: [], organizationId: "", catalog: [],
    view: "dashboard", authMode: "login", file: null, profile: null, confirmation: null,
    documentType: "inventory_report", runs: [], detailCache: {},
    latestInventoryRun: null, latestInventory: null, latestSalesRun: null, latestSales: null,
    overstock: null, inventoryHistory: null, selectedRun: null, targetDays: 30
  };

  function esc(v) {
    return String(v === undefined || v === null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function nice(v) {
    if (v === undefined || v === null || v === "") return "—";
    if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toLocaleString("en-IN", { maximumFractionDigits: 3 });
    return String(v);
  }
  function todayISO() {
    const d = new Date();
    return [d.getFullYear(), String(d.getMonth()+1).padStart(2,"0"), String(d.getDate()).padStart(2,"0")].join("-");
  }
  function errText(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map(x => x.msg || JSON.stringify(x)).join(" · ");
    return detail && typeof detail === "object" ? JSON.stringify(detail) : "The request could not be completed.";
  }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set("Authorization", "Bearer " + state.token);
    let body = options.body;
    if (options.json !== undefined) { headers.set("Content-Type", "application/json"); body = JSON.stringify(options.json); }
    const response = await fetch(path, { ...options, headers, body });
    const raw = await response.text();
    let data = {};
    if (raw) { try { data = JSON.parse(raw); } catch { data = { detail: raw }; } }
    if (!response.ok) throw new Error(errText(data.detail || data.message || response.statusText) + " (HTTP " + response.status + ")");
    return data;
  }
  function notify(message, isError = false) {
    const toast = $("#toast"); toast.textContent = message; toast.classList.toggle("error", isError); toast.hidden = false;
    window.clearTimeout(notify.timer); notify.timer = window.setTimeout(() => { toast.hidden = true; }, 4500);
  }
  function authError(message) { const node = $("#authError"); node.textContent = message; node.hidden = !message; }
  function setApiStatus(status, label) {
    const node = $("#apiStatus"); node.className = "api-status " + status;
    node.innerHTML = '<span class="status-dot"></span><span></span>'; $("span:last-child", node).textContent = label;
  }

  function renderAuthForm() {
    const register = state.authMode === "register";
    $("#authTitle").textContent = register ? "Create your account" : "Welcome back";
    $("#authSubtitle").textContent = register ? "Create a sign-in for your private workspace." : "Sign in to review your organization's inventory signals.";
    $$("[data-auth-mode]").forEach(button => {
      const active = button.dataset.authMode === state.authMode;
      button.classList.toggle("active", active); button.setAttribute("aria-selected", active ? "true" : "false");
    });
    $("#authFormMount").innerHTML = '<form id="authForm" novalidate>' +
      '<div class="field"><label for="authEmail">Email address</label><input id="authEmail" name="email" type="email" autocomplete="email" required maxlength="254" placeholder="you@pharmacy.in"></div>' +
      '<div class="field"><label for="authPassword">Password</label><input id="authPassword" name="password" type="password" autocomplete="' + (register ? "new-password" : "current-password") + '" required minlength="12" maxlength="128" placeholder="' + (register ? "At least 12 characters" : "Your password") + '"><small class="helper">' + (register ? "Use a strong, unique password. A demo-only account is fine." : "Access tokens expire after 30 minutes.") + '</small></div>' +
      '<button class="primary-button full-width auth-submit" type="submit">' + (register ? "Create account" : "Sign in") + ' <span aria-hidden="true">→</span></button></form>';
    $("#authForm").addEventListener("submit", handleAuth); authError("");
  }
  async function handleAuth(event) {
    event.preventDefault(); authError("");
    const form = new FormData(event.currentTarget), email = String(form.get("email") || "").trim(), password = String(form.get("password") || "");
    if (!email || !password) { authError("Enter your email and password."); return; }
    if (password.length < 12) { authError("Use at least 12 characters for the password."); return; }
    const button = $("button[type=submit]", event.currentTarget); button.disabled = true; button.textContent = "Connecting…";
    try {
      const endpoint = state.authMode === "register" ? "/api/v1/auth/register" : "/api/v1/auth/token";
      const result = await api(endpoint, { method: "POST", json: { email, password } });
      state.token = result.access_token; state.user = result.user;
      $("#authScreen").hidden = true; $("#workspace").hidden = false;
      $("#userEmail").textContent = state.user.email; $("#userAvatar").textContent = (state.user.email || "U").slice(0,1).toUpperCase();
      state.catalog = (await api("/api/v1/schema/fields")).fields || [];
      await loadOrganizations();
      notify(state.authMode === "register" ? "Account created. Create or select an organization to continue." : "Welcome back.");
    } catch (error) { authError(error.message || "Could not sign in."); }
    finally {
      const current = $("#authForm button[type=submit]");
      if (current) { current.disabled = false; current.textContent = state.authMode === "register" ? "Create account →" : "Sign in →"; }
    }
  }
  async function loadOrganizations() {
    const result = await api("/api/v1/organizations"); state.organizations = result.organizations || [];
    if (!state.organizations.some(org => org.organization_id === state.organizationId)) state.organizationId = state.organizations[0]?.organization_id || "";
    renderOrgSelect();
    if (!state.organizationId) { state.view = "workspace"; renderView(); return; }
    await refreshRuns(); renderView();
  }
  function renderOrgSelect() {
    const select = $("#orgSelect");
    if (!state.organizations.length) { select.innerHTML = '<option value="">No organization yet</option>'; select.disabled = true; return; }
    select.innerHTML = state.organizations.map(org => '<option value="' + esc(org.organization_id) + '">' + esc(org.display_name) + ' · ' + esc(org.organization_id.slice(0, 8)) + ' · ' + esc(org.role) + "</option>").join("");
    select.value = state.organizationId; select.disabled = false;
  }
  async function refreshRuns() {
    if (!state.organizationId) return;
    const response = await api("/api/v1/normalization-runs?organization_id=" + encodeURIComponent(state.organizationId) + "&limit=50");
    state.runs = response.runs || [];
    state.latestInventoryRun = state.runs.find(run => run.document_type === "inventory_report") || null;
    state.latestSalesRun = state.runs.find(run => run.document_type === "retail_sales") || null;
    state.latestInventory = null; state.latestSales = null; state.overstock = null; state.inventoryHistory = null;
    const jobs = [];
    if (state.latestInventoryRun) jobs.push(loadRunDetail(state.latestInventoryRun.normalization_run_id).then(data => { state.latestInventory = data; }).catch(() => {}));
    if (state.latestSalesRun) jobs.push(loadRunDetail(state.latestSalesRun.normalization_run_id).then(data => { state.latestSales = data; }).catch(() => {}));
    await Promise.all(jobs);
    if (state.latestInventoryRun) {
      const asOf = state.latestInventoryRun.options_summary?.snapshot_date || state.latestInventory?.previews?.inventory_snapshots?.[0]?.snapshot_date || todayISO();
      try { state.inventoryHistory = await api("/api/v1/inventory-history?organization_id=" + encodeURIComponent(state.organizationId) + "&as_of_date=" + encodeURIComponent(asOf)); }
      catch (error) { state.inventoryHistory = { status: "unavailable", error: error.message, series: [] }; }
    }
    if (state.latestInventoryRun && state.latestSalesRun) await refreshOverstock();
  }
  async function loadRunDetail(runId) {
    if (state.detailCache[runId]) return state.detailCache[runId];
    const result = await api("/api/v1/normalization-runs/" + encodeURIComponent(runId) + "?organization_id=" + encodeURIComponent(state.organizationId));
    state.detailCache[runId] = result; return result;
  }
  async function refreshOverstock() {
    if (!state.latestSalesRun || !state.latestInventoryRun) { state.overstock = null; return; }
    const asOf = state.latestInventoryRun.options_summary?.snapshot_date || state.latestInventory?.previews?.inventory_snapshots?.[0]?.snapshot_date || todayISO();
    const params = new URLSearchParams({ organization_id: state.organizationId, sales_run_id: state.latestSalesRun.normalization_run_id, as_of_date: asOf, target_days_of_supply: String(state.targetDays) });
    try { state.overstock = await api("/api/v1/overstock-review?" + params.toString()); }
    catch (error) { state.overstock = { status: "unavailable", error: error.message, summary: {}, findings: [] }; }
  }
  function currentOrg() { return state.organizations.find(org => org.organization_id === state.organizationId) || null; }
  function badge(value) {
    const status = String(value || "unknown"); let tone = "info";
    if (status === "ready") tone = "ready";
    else if (status.includes("warning") || status === "unknown" || status === "loading") tone = "warning";
    else if (status.includes("insufficient") || status === "unavailable" || status.includes("error")) tone = "danger";
    return '<span class="status-badge ' + tone + '">' + esc(status.replace(/_/g, " ")) + "</span>";
  }
  function pageHeader(eyebrow, title, description, action = "") {
    return '<div class="page-header"><div><span class="eyebrow">' + esc(eyebrow) + '</span><h1>' + esc(title) + '</h1><p>' + esc(description) + '</p></div>' + (action ? '<div class="page-actions">' + action + "</div>" : "") + "</div>";
  }
  function kpi(label, value, detail) {
    return '<div class="kpi-card"><div class="kpi-label">' + esc(label) + '</div><div class="kpi-number">' + esc(nice(value)) + '</div><div class="kpi-sub">' + esc(detail || "") + "</div></div>";
  }
  function panelHeading(title, description, action = "") {
    return '<div class="panel-heading"><div><h2>' + esc(title) + '</h2>' + (description ? '<p>' + esc(description) + "</p>" : "") + "</div>" + action + "</div>";
  }
  function table(headers, rows, emptyMessage = "Nothing to show yet.") {
    if (!rows || !rows.length) return '<div class="empty-state compact-empty"><span class="empty-icon">↗</span><h3>Nothing to show yet</h3><p>' + esc(emptyMessage) + "</p></div>";
    return '<div class="table-wrap"><table class="data-table"><thead><tr>' + headers.map(x => "<th>" + esc(x) + "</th>").join("") + "</tr></thead><tbody>" +
      rows.map(row => "<tr>" + row.map(cell => "<td>" + esc(nice(cell)) + "</td>").join("") + "</tr>").join("") + "</tbody></table></div>";
  }
  function dateLabel(value) {
    if (!value) return "—";
    try { return new Date(value + (String(value).length === 10 ? "T00:00:00" : "")).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); }
    catch { return String(value); }
  }
  function dayAge(asOfDate, snapshotDate) {
    if (!asOfDate || !snapshotDate) return "—";
    const asOf = Date.parse(String(asOfDate).slice(0, 10) + "T00:00:00Z");
    const snapshot = Date.parse(String(snapshotDate).slice(0, 10) + "T00:00:00Z");
    if (!Number.isFinite(asOf) || !Number.isFinite(snapshot) || snapshot > asOf) return "—";
    return Math.floor((asOf - snapshot) / 86400000);
  }
  function renderView() {
    $$ (".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
    const titles = { dashboard: "Overview", upload: "Import & analyze", history: "Inventory history", reports: "Insights & reports", workspace: "Create workspace" };
    $("#pageTitle").textContent = titles[state.view] || "Overview";
    if (!state.organizationId) {
      $("#mainContent").innerHTML = pageHeader("GET STARTED", "Create your workspace", "Each organization is isolated from other workspaces.") +
        '<div class="workspace-empty"><span class="empty-icon">＋</span><h2>Your first organization</h2><p>Create a workspace for your pharmacy, stockist, or synthetic test data. Membership is checked by the API before any run is saved.</p><form id="createOrgForm"><div class="field"><label for="orgName">Organization name</label><input id="orgName" required maxlength="200" minlength="2" placeholder="e.g. Demo Pharmacy"></div><button type="submit" class="primary-button full-width">Create organization →</button></form></div>';
      $("#createOrgForm").addEventListener("submit", handleCreateOrganization); return;
    }
    if (state.view === "upload") renderUpload();
    else if (state.view === "history") renderHistory();
    else if (state.view === "reports") renderReports();
    else renderDashboard();
  }
  async function handleCreateOrganization(event) {
    event.preventDefault(); const input = $("#orgName"), name = input.value.trim();
    if (name.length < 2) { input.focus(); return; }
    try {
      const result = await api("/api/v1/organizations", { method: "POST", json: { display_name: name } });
      state.organizations.push({ organization_id: result.organization_id, display_name: result.display_name, role: result.role });
      state.organizationId = result.organization_id; renderOrgSelect(); state.view = "dashboard";
      await refreshRuns(); renderView(); notify("Workspace created.");
    } catch (error) { notify(error.message, true); }
  }
  function renderDashboard() {
    const org = currentOrg(), runCount = state.runs.length;
    const inventory = state.latestInventory?.quality_report?.inventory_analysis || {};
    const forecast = state.latestSales?.quality_report?.forecasting_baseline || {};
    const expiryCount = inventory.summary?.expiry_alert_count ?? (inventory.expiry_alerts || []).length;
    const aboveTarget = state.overstock?.summary?.above_target_count ?? "—";
    const demandCount = (forecast.forecasts || []).length;
    const expiryRows = (inventory.expiry_alerts || []).slice(0, 4).map(row => [row.product_name || row.product_id, row.batch_code, dateLabel(row.expiry_date), row.days_to_expiry, nice(row.quantity_on_hand) + " " + (row.quantity_unit || "")]);
    const empty = '<div class="empty-state"><span class="empty-icon">↥</span><h3>No uploaded files yet</h3><p>Import an invoice, dated inventory snapshot, or retail-sales extract. Start with synthetic data while testing.</p><button class="primary-button" type="button" data-view="upload">Import first file →</button></div>';
    $("#mainContent").innerHTML = pageHeader("WORKSPACE OVERVIEW", "Inventory overview", "Welcome to " + (org?.display_name || "your organization") + ". Here is the latest saved data available to this workspace.", '<button type="button" class="primary-button" data-view="upload">＋ Import data</button>') +
      '<div class="kpi-grid">' + kpi("Saved normalization runs", runCount, "Across this organization") +
      kpi("Expiry alerts", inventory.status ? expiryCount : "—", inventory.as_of_date ? "As of " + dateLabel(inventory.as_of_date) : "Upload an inventory snapshot") +
      kpi("Product demand baselines", demandCount, forecast.status ? "Baseline only · not validated" : "Upload complete retail sales") +
      kpi("Above target supply", aboveTarget, state.overstock?.status ? "Rule-based stock review" : "Needs saved inventory and sales") + '</div>' +
      '<div class="split-grid"><section class="panel">' + panelHeading("Expiry watch", "Positive stock in batches with usable expiry evidence.", '<button class="text-link" data-view="reports">View insights →</button>') +
      (inventory.status ? '<div class="metric-line"><span>Report date</span><strong>' + esc(dateLabel(inventory.as_of_date)) + '</strong></div><div class="metric-line"><span>Analysis status</span><strong>' + badge(inventory.status) + '</strong></div>' + table(["Product", "Batch", "Expiry", "Days left", "On hand"], expiryRows, "No expiry alerts in the latest saved inventory run.") : empty) +
      '</section><section class="panel">' + panelHeading("Data readiness", "Analysis depends on what the source actually contains.") +
      '<div class="metric-line"><span>Inventory history</span><strong>' + badge(state.inventoryHistory?.status || (state.latestInventory ? "loading" : "not available")) + '</strong></div>' +
      '<div class="metric-line"><span>Demand baseline</span><strong>' + badge(forecast.status || "insufficient_data") + '</strong></div>' +
      '<div class="metric-line"><span>Overstock review</span><strong>' + badge(state.overstock?.status || "insufficient_data") + '</strong></div><div class="section-divider"></div>' +
      '<div class="callout"><span class="callout-icon">i</span><div><strong>Not a purchase order recommendation</strong><p>The stock target is a configurable assumption. Lead times, incoming orders and expiry-aware allocation are not included.</p></div></div></section></div>' +
      '<section class="panel" style="margin-top:15px">' + panelHeading("Recent uploads", "Saved run history for the selected organization.", '<button class="text-link" data-view="reports">All insights →</button>') +
      (runCount ? table(["Source file", "Document type", "Rows", "Products", "Status", "Saved"], state.runs.slice(0,8).map(run => [run.source_file_name, run.document_type.replace(/_/g," "), nice(run.input_row_count), nice(run.summary?.product_count || 0), run.normalization_status || "completed", dateLabel(run.created_at)]), "No saved runs") +
      '<div class="page-actions" style="margin-top:14px"><button class="secondary-button" data-view="history">Open inventory history</button><button class="secondary-button" data-view="upload">Import another file</button></div>' : empty) + '</section>';
  }

  function docTypeOptions(selected) {
    const types = [["inventory_report","Inventory snapshot"],["retail_sales","Retail sales / sell-through"],["purchase_invoice","Purchase invoice"],["outward_invoice","Outward / dispatch invoice"],["unknown","Not sure yet"]];
    return types.map(([v,label]) => '<option value="' + v + '"' + (selected === v ? " selected" : "") + ">" + label + "</option>").join("");
  }
  function renderUpload() {
    const profileReady = Boolean(state.profile && state.file), confirmed = Boolean(state.confirmation);
    const profile = state.profile || {}, columns = profile.columns || [];
    const mappingSection = profileReady ? '<section class="panel" id="mappingPanel" style="margin-top:15px">' +
      panelHeading("Step 2 · Review every column", "Suggestions are a starting point. Confirm or ignore each column and provide required units, date formats and movement types.") +
      '<div class="callout" style="margin-bottom:14px"><span class="callout-icon">!</span><div><strong>Explicit decisions required</strong><p>Missing or ambiguous units and date conventions must be corrected before normalization. Ignored columns remain visible in the confirmation payload.</p></div></div>' +
      '<p class="small-copy">Profiled ' + esc(nice(profile.row_count_profiled)) + ' rows · ' + esc(nice(profile.column_count)) + ' columns · ' + (profile.truncated ? "The profile is truncated; reduce the file before normalizing." : "Profile complete within current limits.") + '</p>' +
      ((profile.warnings || []).length ? '<div class="form-message error-message">' + profile.warnings.map(esc).join("<br>") + "</div>" : "") +
      '<div class="table-wrap" style="margin-top:13px"><table class="data-table schema-table"><thead><tr><th>Source column</th><th>Detected</th><th>Map to canonical field</th><th>Required metadata</th></tr></thead><tbody>' +
      columns.map((column,i) => renderSchemaRow(column,i)).join("") + '</tbody></table></div>' +
      '<div id="mappingError" class="form-message error-message" role="alert" hidden></div>' +
      '<div class="page-actions" style="margin-top:15px"><button type="button" class="secondary-button" data-action="clear-profile">Start over</button><button type="button" class="primary-button" id="confirmMappingButton" ' + (profile.truncated ? "disabled" : "") + (confirmed ? " disabled" : "") + '>Confirm mapping decisions →</button></div>' +
      (confirmed ? '<div style="margin-top:18px"><div class="confirmed-banner"><span>✓</span> Mapping decisions confirmed. Review context and normalize this file.</div>' + renderOptionsForm() + '</div>' : "") +
      '</section>' : "";
    $("#mainContent").innerHTML = pageHeader("DATA INGESTION", "Import & analyze", "Profile a source file, confirm every column mapping, then normalize and save it to the selected organization.") +
      '<section class="panel">' + panelHeading("Step 1 · Select source file", "CSV or XLSX · maximum 10 MB · original upload bytes are not stored by the normalization workflow.") +
      '<form id="profileForm"><div class="form-grid">' +
      '<div class="field"><label for="documentType">What does this file represent?</label><select id="documentType" name="document_type">' + docTypeOptions(state.documentType) + '</select><small class="helper">Purchases and stockist dispatches are movements, not retail demand or on-hand stock.</small></div>' +
      '<div class="field"><label for="sourceFile">Choose CSV or Excel</label><div class="upload-drop" id="uploadDrop"><span class="upload-symbol">↥</span><div><strong>Choose a file to profile</strong><p id="selectedFileName">' + (state.file ? esc(state.file.name) : "CSV or XLSX, up to 10 MB") + '</p><input id="sourceFile" name="file" type="file" accept=".csv,.xlsx" required></div></div></div></div>' +
      '<div class="page-actions"><button class="primary-button" id="profileButton" type="submit">Profile file →</button></div></form></section>' + mappingSection;
    const fileInput = $("#sourceFile");
    fileInput.addEventListener("change", () => {
      state.file = fileInput.files?.[0] || null; $("#selectedFileName").textContent = state.file ? state.file.name : "CSV or XLSX, up to 10 MB";
      state.profile = null; state.confirmation = null;
      const mapping = $("#mappingPanel"); if (mapping) mapping.remove();
    });
    $("#documentType").addEventListener("change", event => {
      state.documentType = event.target.value;
      if (state.profile) { state.confirmation = null; renderUpload(); }
    });
    $("#profileForm").addEventListener("submit", handleProfile);
    const drop = $("#uploadDrop");
    ["dragenter","dragover"].forEach(name => drop.addEventListener(name,event => {event.preventDefault();drop.classList.add("drag-over");}));
    ["dragleave","drop"].forEach(name => drop.addEventListener(name,event => {event.preventDefault();drop.classList.remove("drag-over");}));
    drop.addEventListener("drop",event => {
      const file = event.dataTransfer?.files?.[0]; if (!file) return;
      state.file = file; $("#selectedFileName").textContent = file.name; state.profile = null; state.confirmation = null;
      const mapping = $("#mappingPanel"); if (mapping) mapping.remove(); notify("File selected. Press Profile file to inspect its columns.");
    });
    if (profileReady && !confirmed) {
      $("#confirmMappingButton").addEventListener("click", handleConfirmSchema);
      $$("[data-role=canonical]").forEach(select => select.addEventListener("change", () => syncMetaRow(select.dataset.index)));
      $$("[data-role=meta]").forEach(control => control.addEventListener("change", () => { if ($("#mappingError")) $("#mappingError").hidden = true; }));
      columns.forEach(column => syncMetaRow(column.column_index));
    }
  }
  function options(values, current, placeholder) {
    return '<option value="">' + esc(placeholder) + "</option>" + values.map(entry => {
      const value = Array.isArray(entry) ? entry[0] : entry, label = Array.isArray(entry) ? entry[1] : entry;
      return '<option value="' + esc(value) + '"' + (String(current || "") === String(value) ? " selected" : "") + ">" + esc(label) + "</option>";
    }).join("");
  }
  function renderSchemaRow(column,index) {
    const names = new Set(state.catalog.map(field => field.name)), suggestion = column.mapping?.canonical_field;
    const current = suggestion && names.has(suggestion) ? suggestion : "", source = column.source_column;
    const normalized = String(source).toLowerCase().replace(/[^a-z0-9]/g,"");
    const composite = ["qtyfree","quantityfree"].includes(normalized), locked = state.confirmation ? " disabled" : "";
    const fields = state.catalog.map(field => [field.name, field.name + " — " + field.description]);
    return '<tr data-schema-row="' + index + '"><td><strong>' + esc(source) + '</strong><span class="mapping-hint">Column ' + (index+1) + ' · ' + esc(column.unique_count) + ' unique</span><span class="mapping-hint">' + esc(column.missing_percent) + '% missing</span></td><td>' + esc(column.detected_type || "unknown") + '</td>' +
      '<td class="mapping-choice"><select class="control-select" data-role="canonical" data-index="' + index + '" aria-label="Map ' + esc(source) + ' to"' + locked + '>' + options(fields,current,"Ignore column") + '</select></td><td><div class="meta-controls">' +
      '<input class="control-input" data-role="meta" data-meta="quantity_unit" data-index="' + index + '" placeholder="Unit (e.g. pack)" aria-label="Quantity unit for ' + esc(source) + '"' + locked + '>' +
      '<select class="control-select" data-role="meta" data-meta="transaction_type" data-index="' + index + '" aria-label="Movement type for ' + esc(source) + '"' + locked + '>' + options(MOVEMENT_TYPES,"","Select movement type") + '</select>' +
      '<select class="control-select" data-role="meta" data-meta="date_format" data-index="' + index + '" aria-label="Date format for ' + esc(source) + '"' + locked + '>' + options(DATE_FORMATS,"","Confirm date format") + '</select>' +
      '<select class="control-select" data-role="meta" data-meta="date_convention" data-index="' + index + '" aria-label="Expiry convention for ' + esc(source) + '"' + locked + '>' + options([["month_end","Month/year means month-end"]],"","Date convention") + '</select>' +
      (composite ? '<select class="control-select" data-role="meta" data-meta="transformation_rule" data-index="' + index + '" aria-label="QTY+FREE transformation"' + locked + '>' + options([["split_quantity_and_free","Split paid + free qty"]],"","Select split rule") + '</select><label class="inline-check"><input type="checkbox" data-role="meta" data-meta="free_quantity" data-index="' + index + '"' + locked + '> Also map <code>free_quantity</code></label>' : '') +
      '<span class="meta-note" data-meta-note="' + index + '">Required metadata appears when relevant to the selected field.</span></div></td></tr>';
  }
  function syncMetaRow(index) {
    const row = document.querySelector('[data-schema-row="' + index + '"]'); if (!row) return;
    const canonical = $("[data-role=canonical]",row).value, isDate = DATE_FIELDS.has(canonical), isQuantity = QUANTITY_FIELDS.has(canonical), isQty = canonical === "quantity";
    const source = String(state.profile?.columns?.[Number(index)]?.source_column || "").toLowerCase().replace(/[^a-z0-9]/g,"");
    const composite = ["qtyfree","quantityfree"].includes(source) && isQty;
    $$("[data-role=meta]",row).forEach(control => {
      const field = control.dataset.meta;
      const unavailable = !canonical || (field === "quantity_unit" && !isQuantity) || (field === "transaction_type" && !isQty) ||
        (field === "date_format" && !isDate) || (field === "date_convention" && !(canonical === "expiry_date" && ["MM/YY","MM/YYYY"].includes($('[data-meta=date_format]',row).value))) ||
        (field === "transformation_rule" && !composite) || (field === "free_quantity" && !composite);
      control.disabled = Boolean(state.confirmation) || unavailable;
      if (control.disabled && control.type === "checkbox") control.checked = false;
    });
    const note = $('[data-meta-note="' + index + '"]',row);
    if (note) {
      const required = []; if (isDate) required.push("date format"); if (isQuantity) required.push("unit"); if (isQty) required.push("movement type");
      if (canonical === "expiry_date") required.push("month-end convention for month/year values");
      if (composite) required.push("QTY+FREE split rule and free-quantity field");
      note.textContent = required.length ? "Confirm: " + required.join(", ") + "." : "No additional metadata required for this field.";
    }
  }
  async function handleProfile(event) {
    event.preventDefault();
    const file = state.file || $("#sourceFile").files?.[0], type = $("#documentType").value;
    if (!file) { notify("Choose a file first.",true); return; }
    if (!/\.(csv|xlsx)$/i.test(file.name)) { notify("Only CSV and XLSX files are supported.",true); return; }
    if (file.size > 10*1024*1024) { notify("This file is larger than the 10 MB limit.",true); return; }
    state.file = file; state.documentType = type; state.profile = null; state.confirmation = null;
    const button = $("#profileButton"); button.disabled = true; button.textContent = "Profiling…";
    try {
      const form = new FormData(); form.append("file",file,file.name); state.profile = await api("/api/v1/profile",{method:"POST",body:form});
      renderUpload(); notify(state.profile.truncated ? "Profile reached the row limit. Reduce the file before normalization." : "Profile complete. Review every column before confirming.", Boolean(state.profile.truncated));
    } catch (error) { notify(error.message,true); }
    finally { const current = $("#profileButton"); if (current) {current.disabled=false;current.textContent="Profile file →";} }
  }
  function collectSchema() {
    if (!state.profile || !state.file) throw new Error("Profile a file before confirming the schema.");
    const profiled_columns = state.profile.columns.map(column => ({ column_index:Number(column.column_index),source_column:String(column.source_column) }));
    const mappings = [];
    for (const column of profiled_columns) {
      const row = document.querySelector('[data-schema-row="' + column.column_index + '"]'), canonical = $("[data-role=canonical]",row).value;
      if (!canonical) { mappings.push({...column,action:"ignore"}); continue; }
      const item = {...column,action:"map",canonical_field:canonical};
      const read = name => $('[data-meta="' + name + '"]',row)?.value || "";
      if (DATE_FIELDS.has(canonical)) {
        item.date_format = read("date_format");
        if (!item.date_format) throw new Error('Choose a date format for column "' + column.source_column + '".');
        if (canonical === "expiry_date" && ["MM/YY","MM/YYYY"].includes(item.date_format)) {
          item.date_convention = read("date_convention");
          if (!item.date_convention) throw new Error('Confirm the month-end convention for "' + column.source_column + '".');
        }
      }
      if (QUANTITY_FIELDS.has(canonical)) {
        item.quantity_unit = read("quantity_unit").trim();
        if (!item.quantity_unit) throw new Error('Enter a quantity unit for "' + column.source_column + '" (e.g. pack, strip, tablet).');
      }
      if (canonical === "quantity") {
        item.transaction_type = read("transaction_type");
        if (!item.transaction_type) throw new Error('Select a movement type for "' + column.source_column + '".');
      }
      const src = column.source_column.toLowerCase().replace(/[^a-z0-9]/g,"");
      if (canonical === "quantity" && ["qtyfree","quantityfree"].includes(src)) {
        item.transformation_rule = read("transformation_rule");
        if (!item.transformation_rule || !$('[data-meta="free_quantity"]',row)?.checked) {
          throw new Error('For "' + column.source_column + '", select the split rule and confirm free_quantity.');
        }
        item.additional_canonical_fields = ["free_quantity"];
      }
      mappings.push(item);
    }
    return {profiled_columns,mappings};
  }
  async function handleConfirmSchema() {
    const errorNode = $("#mappingError"); errorNode.hidden = true; let schema;
    try { schema = collectSchema(); } catch(error) {errorNode.textContent=error.message;errorNode.hidden=false;return;}
    const button = $("#confirmMappingButton"); button.disabled=true;button.textContent="Validating…";
    try {
      const result = await api("/api/v1/schema/confirm",{method:"POST",json:schema});
      if (result.schema_status !== "confirmed") throw new Error("The API did not confirm the schema.");
      state.confirmation = schema; renderUpload(); notify("Column mappings confirmed.");
    } catch(error) {
      errorNode.textContent=error.message;errorNode.hidden=false;
      const current=$("#confirmMappingButton");if(current){current.disabled=false;current.textContent="Confirm mapping decisions →";}
    }
  }
  function renderOptionsForm() {
    return '<section class="panel" style="margin-top:14px;background:#fbfdfb">' + panelHeading("Step 3 · Confirm context & normalize","Completeness and stock basis are explicit attestations; leave them unconfirmed unless the source owner verifies them.") +
      '<form id="optionsForm"><div class="form-grid">' +
      '<div class="field"><label for="ctxDocType">Document type</label><select id="ctxDocType" disabled>' + docTypeOptions(state.documentType) + '</select></div>' +
      '<div class="field"><label for="ctxCurrency">Currency code</label><input id="ctxCurrency" maxlength="3" minlength="3" value="INR" placeholder="INR"><small class="helper">Change this to match the source document.</small></div>' +
      '<div class="field"><label for="ctxCounterparty">Counterparty ID (optional)</label><input id="ctxCounterparty" maxlength="200" placeholder="Use a pseudonymous supplier / outlet ID"></div>' +
      '<div class="field" id="snapshotDateField"><label for="ctxSnapshotDate">Inventory snapshot date</label><input id="ctxSnapshotDate" type="date" value="' + todayISO() + '"><small class="helper">Used as the historical report date for expiry calculations.</small></div></div>' +
      '<div id="inventoryOptions"><label class="inline-check"><input type="checkbox" id="ctxInventoryComplete"> I confirm this snapshot includes every in-scope on-hand position.</label><div class="field" style="max-width:420px"><label for="ctxStockBasis">Stock basis</label><select id="ctxStockBasis"><option value="">Unknown / not confirmed</option><option value="physical">Physical counted stock</option><option value="system">System-reported stock</option></select><small class="helper">Do not select a basis unless the source owner has verified it.</small></div></div>' +
      '<div id="salesOptions"><label class="inline-check"><input type="checkbox" id="ctxSalesComplete"> I confirm this file includes every sale and every zero-sale day for a continuous date range.</label><div class="form-grid"><div class="field"><label for="ctxSalesStart">History start date</label><input id="ctxSalesStart" type="date"></div><div class="field"><label for="ctxSalesEnd">History end date</label><input id="ctxSalesEnd" type="date"></div></div></div>' +
      '<div class="section-divider"></div><label class="inline-check"><input type="checkbox" id="ctxPersist" checked> Save normalized records and analysis results to this organization.</label><p class="small-copy">The API checks your organization role before saving. Original upload bytes are not stored. Preview-only processing can be used by read-only members.</p>' +
      '<div id="optionsError" class="form-message error-message" role="alert" hidden></div><div class="page-actions" style="margin-top:15px"><button type="button" class="secondary-button" id="backToMapping">← Review mappings</button><button type="submit" class="primary-button" id="normalizeButton">Normalize &amp; analyze →</button></div></form></section>';
  }
  function readOptions() {
    const docType = state.documentType, options = {organization_id:state.organizationId,document_type:docType};
    const currency = $("#ctxCurrency").value.trim().toUpperCase();
    if (currency) {if(currency.length!==3)throw new Error("Currency code must contain exactly three letters.");options.currency_code=currency;}
    const cp = $("#ctxCounterparty").value.trim(); if(cp)options.counterparty_id=cp;
    if(docType==="inventory_report"){
      const d=$("#ctxSnapshotDate").value;if(!d)throw new Error("Set the date of this inventory snapshot.");
      options.snapshot_date=d;options.inventory_snapshot_complete=$("#ctxInventoryComplete").checked;
      const basis=$("#ctxStockBasis").value;if(basis)options.inventory_stock_basis=basis;
    }
    if(docType==="retail_sales"){
      const complete=$("#ctxSalesComplete").checked;options.sales_history_complete=complete;
      if(complete){
        const start=$("#ctxSalesStart").value,end=$("#ctxSalesEnd").value;
        if(!start||!end)throw new Error("Set both ends of the confirmed sales-history period.");
        if(start>end)throw new Error("History start date must be on or before the end date.");
        const days=Math.round((new Date(end+"T00:00:00")-new Date(start+"T00:00:00"))/86400000)+1;
        if(days<49)throw new Error("The baseline evaluator needs at least 49 calendar days of declared history.");
        options.sales_history_start_date=start;options.sales_history_end_date=end;
      }
    }
    return options;
  }
  async function handleNormalize(event) {
    event.preventDefault();const errorNode=$("#optionsError");errorNode.hidden=true;
    if(!state.confirmation||!state.file){errorNode.textContent="Confirm the schema before normalizing.";errorNode.hidden=false;return;}
    let options;try{options=readOptions();}catch(error){errorNode.textContent=error.message;errorNode.hidden=false;return;}
    const save=$("#ctxPersist").checked,button=$("#normalizeButton");button.disabled=true;button.textContent="Normalizing…";
    try{
      const form=new FormData();form.append("file",state.file,state.file.name);form.append("confirmed_schema_json",JSON.stringify(state.confirmation));
      form.append("options_json",JSON.stringify(options));form.append("persist",save?"true":"false");
      const result=await api("/api/v1/normalize",{method:"POST",body:form});
      state.detailCache={};state.selectedRun=result;
      if(result.normalization_run_id){
        await refreshRuns();
        const run=state.runs.find(item=>item.normalization_run_id===result.normalization_run_id);
        if(run)state.selectedRun=await loadRunDetail(run.normalization_run_id).catch(()=>result);
      }
      state.view="reports";renderView();notify(save?"Normalization completed and saved.":"Preview complete. Nothing was saved.");
    }catch(error){errorNode.textContent=error.message;errorNode.hidden=false;}
    finally{const current=$("#normalizeButton");if(current){current.disabled=false;current.textContent="Normalize & analyze →";}}
  }
  function renderUploadWrapper() {
    const observer = new MutationObserver(() => {
      const form=$("#optionsForm");
      if(form&&!form.dataset.bound){
        form.dataset.bound="true";form.addEventListener("submit",handleNormalize);
        $("#backToMapping").addEventListener("click",()=>{state.confirmation=null;renderUpload();});
      }
    });
    observer.observe($("#mainContent"),{childList:true,subtree:true});
  }
  async function renderHistory() {
    const run = state.latestInventoryRun;
    const asOf = run?.options_summary?.snapshot_date
      || state.latestInventory?.previews?.inventory_snapshots?.[0]?.snapshot_date
      || todayISO();
    if (!state.inventoryHistory && run) {
      try {
        state.inventoryHistory = await api(
          "/api/v1/inventory-history?organization_id=" + encodeURIComponent(state.organizationId)
          + "&as_of_date=" + encodeURIComponent(asOf)
        );
      } catch (error) {
        state.inventoryHistory = { status: "unavailable", error: error.message, series: [], warnings: [] };
      }
    }
    const history = state.inventoryHistory;
    const series = history?.series || [];
    const distinctSnapshotDates = new Set(
      series.flatMap(item => (item.history || []).map(point => point.snapshot_date)).filter(Boolean)
    );
    const historySummary = history?.summary || {};
    const unknownLatestCount = Number(historySummary.latest_quantity_unknown_series_count || 0);
    const oneSnapshotNotice = distinctSnapshotDates.size === 1
      ? '<div class="callout" style="margin-top:12px"><span class="callout-icon">i</span><div><strong>Single snapshot only</strong><p>Only one distinct snapshot date is available. This is a current-position listing, not a historical trend; inventory movement between dates cannot be assessed from this upload alone.</p></div></div>'
      : "";
    const rows = series.slice(0, 100).map(item => {
      const latest = item.latest_observation || {};
      const product = item.product || {};
      // latest_quantity_known is a series-level field; the point itself has no such field.
      const latestKnown = item.latest_quantity_known !== false && latest.status !== "conflict";
      const batchDetails = [
        ...(item.batch_codes || []),
        ...(item.expiry_dates || []).map(expiry => "expiry " + expiry)
      ].join(" · ") || "—";
      return [
        product.product_name || item.identity_ref,
        product.source_product_code || "—",
        item.inventory_level,
        batchDetails,
        latest.snapshot_date || "—",
        dayAge(history?.as_of_date || asOf, latest.snapshot_date),
        latestKnown ? latest.quantity_on_hand : "Unknown (conflict / unit ambiguity)",
        item.quantity_units?.join(", ") || latest.quantity_unit || "—",
        item.series_status
      ];
    });
    const historyWarnings = (history?.warnings || []).map(esc);
    const warningNotice = historyWarnings.length
      ? '<div class="callout" style="margin-top:12px"><span class="callout-icon">!</span><div><strong>Inventory history warnings</strong><p>'
        + historyWarnings.join("<br>") + "</p></div></div>"
      : "";
    $("#mainContent").innerHTML = pageHeader(
      "STOCK SNAPSHOTS", "Inventory history",
      "A conservative ledger across saved stock snapshots. It never reconstructs on-hand balances from invoices alone.",
      '<button class="secondary-button" data-action="refresh-workspace">↻ Refresh</button>'
    ) +
      '<section class="panel">' + panelHeading("Snapshot ledger", "Report date: " + dateLabel(history?.as_of_date || asOf)) +
      (history
        ? '<div class="metric-line"><span>Ledger status</span><strong>' + badge(history.status) + '</strong></div>'
          + '<div class="metric-line"><span>Inventory observations</span><strong>' + esc(nice(history.summary?.input_snapshot_count)) + '</strong></div>'
          + '<div class="metric-line"><span>Derived product / batch series</span><strong>' + esc(nice(history.summary?.series_returned ?? series.length)) + '</strong></div>'
          + '<div class="metric-line"><span>Distinct snapshot dates</span><strong>' + esc(nice(distinctSnapshotDates.size)) + '</strong></div>'
          + '<div class="metric-line"><span>Latest quantities unresolved</span><strong>' + esc(nice(unknownLatestCount)) + '</strong></div>'
          + (history.error ? '<div class="form-message error-message">' + esc(history.error) + '</div>' : "")
          + oneSnapshotNotice + warningNotice
          + table(
            ["Product", "SKU", "Level", "Batch / expiry", "Latest snapshot", "Age (days)", "Latest quantity", "Unit", "Series status"],
            rows,
            "No inventory snapshots exist in this organization yet."
          )
          + '</section><section class="panel">' + panelHeading("How to interpret this ledger", "Identity matching is conservative.")
          + '<div class="callout"><span class="callout-icon">i</span><div><strong>Unknown means unknown</strong><p>Conflicting same-date balances, mixed units, or ambiguous cross-upload identity are not automatically resolved. A change between snapshots is not proof of sales, shrinkage or expiry loss.</p></div></div></section>'
        : '<div class="workspace-empty"><span class="empty-icon">↗</span><h2>No inventory history yet</h2><p>Upload a dated inventory snapshot to create the first stock-history entry. Invoice quantities do not count as on-hand balances.</p><button class="primary-button" data-view="upload">Import inventory →</button></div>');
  }
  function renderReports() {
    const inv = state.latestInventory?.quality_report?.inventory_analysis || {};
    const forecast = state.latestSales?.quality_report?.forecasting_baseline || {};
    const expiry = inv.expiry_alerts || [];
    const forecasts = forecast.forecasts || [];
    const overstock = state.overstock || {};
    const findings = overstock.findings || [];
    const selected = state.selectedRun;

    const asOfSources = [
      ["Expiry review", inv.as_of_date],
      ["Inventory history", state.inventoryHistory?.as_of_date],
      ["Overstock review", overstock.as_of_date]
    ].filter(([, value]) => Boolean(value));
    const uniqueAsOfDates = [...new Set(asOfSources.map(([, value]) => value))];
    const dateMismatchNotice = uniqueAsOfDates.length > 1
      ? '<div class="callout" style="margin-top:12px"><span class="callout-icon">!</span><div><strong>Analysis dates do not match</strong><p>'
        + asOfSources.map(([label, value]) => esc(label + ": " + dateLabel(value))).join(" · ")
        + '. These results do not describe one consistent inventory state. Confirm the selected organization and use a consistent saved inventory snapshot before relying on cross-module comparisons.</p></div></div>'
      : "";

    const inventorySource = state.latestInventoryRun;
    const salesSource = state.latestSalesRun;
    const inventorySourceLabel = inventorySource
      ? (inventorySource.source_file_name || inventorySource.document_type) + " · snapshot "
        + dateLabel(inventorySource.options_summary?.snapshot_date || inv.as_of_date)
      : "No saved inventory snapshot selected";
    const salesOptions = salesSource?.options_summary || {};
    const salesSourceLabel = salesSource
      ? (salesSource.source_file_name || salesSource.document_type) + " · "
        + dateLabel(salesOptions.sales_history_start_date) + " – " + dateLabel(salesOptions.sales_history_end_date)
      : "No saved retail-sales history selected";
    const analysisSourcesPanel =
      '<section class="panel">' + panelHeading(
        "Analysis data sources",
        "The selected run shown below is for inspection; these are the saved runs that actually feed the dashboard analyses."
      ) +
      '<div class="metric-line"><span>Inventory / expiry input</span><strong>' + esc(inventorySourceLabel) + '</strong></div>' +
      '<div class="metric-line"><span>Demand / overstock input</span><strong>' + esc(salesSourceLabel) + '</strong></div></section>';

    const inventoryFindings = (inv.findings || []).filter(item => item.severity === "error" || item.severity === "warning");
    const inventoryFindingsNotice = inventoryFindings.length
      ? '<div class="callout" style="margin-top:12px"><span class="callout-icon">!</span><div><strong>Inventory data checks</strong><p>'
        + inventoryFindings.slice(0, 8).map(item =>
          esc(item.severity.toUpperCase() + ": " + item.message + " (affected: " + item.affected_count + ")")
        ).join("<br>")
        + (inventoryFindings.length > 8 ? "<br>Additional findings are omitted from this preview." : "")
        + "</p></div></div>"
      : "";

    const highWapeProducts = forecasts.filter(item =>
      typeof item.rolling_origin_wape_percent === "number" && item.rolling_origin_wape_percent > 100
    );
    const highWapeNotice = highWapeProducts.length
      ? '<div class="callout" style="margin-top:12px"><span class="callout-icon">i</span><div><strong>Review high percentage errors</strong><p>'
        + esc(highWapeProducts.map(item => item.product_name || item.product_id).join(", "))
        + ' have rolling WAPE above 100%. WAPE can exceed 100% when forecast error is larger than total observed sales, especially for low-volume or intermittent products. Review the series before interpreting this metric.</p></div></div>'
      : "";

    const overstockWarnings = (overstock.warnings || []).map(esc);
    const overstockWarningNotice = overstockWarnings.length
      ? '<div class="callout" style="margin-top:12px"><span class="callout-icon">i</span><div><strong>Overstock interpretation limits</strong><p>'
        + overstockWarnings.join("<br>") + "</p></div></div>"
      : "";

    const selectedPanel = selected
      ? '<section class="panel">' + panelHeading(
          "Selected run", selected.source_file_name || selected.document_type || "Preview",
          '<button class="text-link" data-action="clear-selected">Clear selection</button>'
        ) +
        '<div class="metric-line"><span>Document type</span><strong>' + esc(selected.document_type || "Preview only") + '</strong></div>' +
        '<div class="metric-line"><span>Normalization status</span><strong>' + badge(selected.normalization_status || "completed") + '</strong></div>' +
        '<div class="metric-line"><span>Products</span><strong>' + esc(nice(selected.summary?.product_count)) + '</strong></div>' +
        '<div class="metric-line"><span>Transactions / snapshots</span><strong>' + esc(nice(selected.summary?.transaction_count)) + ' / ' + esc(nice(selected.summary?.inventory_snapshot_count)) + '</strong></div>' +
        (selected.quality_report?.analysis_readiness
          ? '<div class="section-divider"></div>' + Object.entries(selected.quality_report.analysis_readiness).map(([key, value]) =>
            '<div class="metric-line"><span>' + esc(key.replace(/_/g, " ")) + '</span><strong>' + badge(value.status || value) + '</strong></div>'
          ).join("")
          : "") + '</section>'
      : "";

    const runRows = state.runs.slice(0, 20).map(run =>
      '<tr><td>' + esc(run.source_file_name) + '</td><td>' + esc(run.document_type.replace(/_/g, " ")) + '</td><td>' +
      esc(nice(run.input_row_count)) + '</td><td>' + esc(nice(run.summary?.product_count || 0)) + '</td><td>' +
      esc(dateLabel(run.created_at)) + '</td><td class="run-id">' + esc(run.normalization_run_id.slice(0, 8)) +
      '…</td><td><button class="text-link" data-action="view-run" data-run-id="' + esc(run.normalization_run_id) + '">View</button></td></tr>'
    ).join("");

    $("#mainContent").innerHTML = pageHeader(
      "ANALYSIS WORKSPACE", "Insights & reports",
      "Expiry alerts, simple demand baselines and stock-target comparisons from saved organization runs.",
      '<button class="primary-button" data-view="upload">＋ Import data</button>'
    ) +
      '<div class="kpi-grid">' +
      kpi("Expiry alerts", inv.status ? (inv.summary?.expiry_alert_count ?? expiry.length) : "—",
        inv.as_of_date ? "Report date " + dateLabel(inv.as_of_date) : "Needs inventory snapshots") +
      kpi("Demand baselines", forecasts.length, forecast.status ? forecast.status.replace(/_/g, " ") : "Needs complete retail-sales history") +
      kpi("Above target", overstock.summary?.above_target_count ?? "—",
        overstock.status ? "Target " + state.targetDays + " days of supply" : "Needs saved stock and sales") +
      kpi("Recent saved runs", state.runs.length, "Up to 50 runs for this organization") +
      '</div>' + selectedPanel + analysisSourcesPanel + dateMismatchNotice +

      '<section class="panel">' + panelHeading("Expiry review", "Positive on-hand batch positions with normalized expiry evidence.") +
      '<div class="metric-line"><span>Analysis status</span><strong>' + badge(inv.status || "insufficient_data") + '</strong></div>' +
      '<div class="metric-line"><span>Report date</span><strong>' + esc(dateLabel(inv.as_of_date)) + '</strong></div>' +
      table(
        ["Alert", "Product", "SKU", "Batch", "Expiry", "Days left", "On hand", "Snapshot / age", "Confidence / caveat"],
        expiry.map(row => [
          row.alert_type, row.product_name, row.source_product_code, row.batch_code, dateLabel(row.expiry_date),
          row.days_to_expiry, nice(row.quantity_on_hand) + " " + (row.quantity_unit || ""),
          dateLabel(row.snapshot_date) + " / " + nice(row.snapshot_age_days) + " days old",
          [row.confidence, ...(row.provisional_reasons || [])].filter(Boolean).join(" · ") || "—"
        ]),
        "No expiry alerts returned. Upload a dated inventory snapshot with valid batch expiry data."
      ) + inventoryFindingsNotice + '</section>' +

      '<section class="panel">' + panelHeading("Demand baseline", "The next-seven-day values are baseline outputs, not production-validated predictions.") +
      '<div class="metric-line"><span>Evaluation status</span><strong>' + badge(forecast.status || "insufficient_data") + '</strong></div>' +
      '<div class="metric-line"><span>History window</span><strong>' + esc(dateLabel(forecast.coverage?.start_date)) + ' – ' + esc(dateLabel(forecast.coverage?.end_date)) + '</strong></div>' +
      table(
        ["Product", "Selected baseline", "Unit", "7-day total", "Next 7 daily values", "Rolling MAE", "Rolling RMSE", "Rolling WAPE %", "Holdout MAE"],
        forecasts.map(item => [
          item.product_name || item.product_id, item.selected_baseline, item.quantity_unit, item.predicted_total_quantity,
          (item.daily_forecast || []).map(day => dateLabel(day.date) + ": " + nice(day.predicted_quantity)).join(" · ") || "—",
          item.rolling_origin_mae, item.rolling_origin_rmse, item.rolling_origin_wape_percent, item.final_holdout_mae
        ]),
        "No forecasts available. Confirm continuous retail sales history of at least 49 days."
      ) + highWapeNotice +
      (forecast.blockers?.length ? '<div class="form-message error-message">' + forecast.blockers.map(esc).join("<br>") + "</div>" : "") +
      (forecast.warnings?.length ? '<p class="small-copy">' + forecast.warnings.map(esc).join("<br>") + "</p>" : "") +
      '</section>' +

      '<section class="panel">' + panelHeading(
        "Overstock review", "Compares stock with a configurable days-of-supply target.",
        '<form id="targetDaysForm" class="page-actions"><label class="field-label" for="targetDaysInput">Target days</label><input id="targetDaysInput" class="control-input" style="width:76px" type="number" min="1" max="365" value="' + esc(state.targetDays) + '"><button class="secondary-button" type="submit">Recalculate</button></form>'
      ) +
      '<div class="metric-line"><span>Analysis status</span><strong>' + badge(overstock.status || "insufficient_data") + '</strong></div>' +
      '<div class="metric-line"><span>Above / within / insufficient data / no demand signal</span><strong>' +
      esc(nice(overstock.summary?.above_target_count ?? "—")) + ' / ' +
      esc(nice(overstock.summary?.within_target_count ?? "—")) + ' / ' +
      esc(nice(overstock.summary?.insufficient_data_count ?? "—")) + ' / ' +
      esc(nice(overstock.summary?.insufficient_demand_signal_count ?? "—")) + '</strong></div>' +
      (overstock.error ? '<div class="form-message error-message">' + esc(overstock.error) + "</div>" : "") +
      table(
        ["Status", "SKU", "Product", "On hand", "Unit", "Avg. daily sales (observed)", "Target stock", "Est. excess", "Days of supply", "Stock snapshot / age", "Review flags"],
        findings.map(row => [
          row.status, row.source_product_code, row.product_name, row.inventory_quantity, row.quantity_unit,
          row.average_daily_demand, row.target_stock_quantity, row.estimated_excess_quantity, row.days_of_supply,
          row.inventory_snapshot_date
            ? dateLabel(row.inventory_snapshot_date) + " / " + nice(row.inventory_snapshot_age_days) + " days old"
            : "—",
          (row.review_flags || []).join(" · ") || "—"
        ]),
        "Requires a saved retail-sales run with confirmed complete history and a compatible recent inventory snapshot."
      ) + overstockWarningNotice +
      '<p class="small-copy">This rule excludes supplier lead times, incoming purchase orders, expiry allocation, seasonality and purchase-cost estimates. Target is a user-supplied policy assumption. Decimal target/excess values come from average sales; they are estimates, not executable pack quantities or purchase instructions.</p>' +
      '</section>' +

      '<section class="panel">' + panelHeading("Saved normalization runs", "Select a run to inspect its status and quality/readiness summary.") +
      (state.runs.length
        ? '<div class="table-wrap"><table class="data-table"><thead><tr><th>File</th><th>Type</th><th>Rows</th><th>Products</th><th>Saved</th><th>Run</th><th></th></tr></thead><tbody>' + runRows + '</tbody></table></div>'
        : '<div class="empty-state"><span class="empty-icon">▤</span><h3>No saved runs</h3><p>Completed normalization runs appear here. Choose preview-only when you do not want to save data.</p></div>'
      ) + '</section>';

    $("#targetDaysForm").addEventListener("submit", async event => {
      event.preventDefault();
      const value = Number($("#targetDaysInput").value);
      if (!Number.isFinite(value) || value < 1 || value > 365) {
        notify("Target days must be between 1 and 365.", true);
        return;
      }
      state.targetDays = value;
      await refreshOverstock();
      renderReports();
      notify("Overstock review recalculated.");
    });
  }
  async function handleViewRun(runId) {
    try{state.selectedRun=await loadRunDetail(runId);state.view="reports";renderView();}
    catch(error){notify(error.message,true);}
  }
  async function handleClick(event) {
    const view=event.target.closest("[data-view]");
    if(view){state.view=view.dataset.view;$("#sidebar").classList.remove("open");renderView();return;}
    const button=event.target.closest("[data-action]");if(!button)return;
    if(button.dataset.action==="refresh-workspace"){
      try{state.detailCache={};await refreshRuns();renderView();notify("Workspace data refreshed.");}
      catch(error){notify(error.message,true);}
    }else if(button.dataset.action==="view-run"){await handleViewRun(button.dataset.runId);}
    else if(button.dataset.action==="clear-selected"){state.selectedRun=null;renderReports();}
    else if(button.dataset.action==="clear-profile"){state.file=null;state.profile=null;state.confirmation=null;renderUpload();}
  }
  async function handleOrgChange(event) {
    if(event.target.id!=="orgSelect")return;
    state.organizationId=event.target.value;state.runs=[];state.detailCache={};state.latestInventory=null;state.latestSales=null;
    state.latestInventoryRun=null;state.latestSalesRun=null;state.overstock=null;state.inventoryHistory=null;
    try{await refreshRuns();state.view="dashboard";renderView();}
    catch(error){notify(error.message,true);}
  }
  function init() {
    renderAuthForm();
    $$("[data-auth-mode]").forEach(button=>button.addEventListener("click",()=>{state.authMode=button.dataset.authMode;renderAuthForm();}));
    $("#orgSelect").addEventListener("change",handleOrgChange);
    $("#logoutButton").addEventListener("click",()=>{
      state.token=null;state.user=null;state.organizations=[];state.organizationId="";state.runs=[];state.detailCache={};
      state.profile=null;state.file=null;state.confirmation=null;$("#workspace").hidden=true;$("#authScreen").hidden=false;state.authMode="login";renderAuthForm();
    });
    $("#mobileMenu").addEventListener("click",()=>$("#sidebar").classList.toggle("open"));
    document.addEventListener("click",handleClick);
    api("/health").then(()=>setApiStatus("ok","API connected")).catch(()=>setApiStatus("error","API unavailable"));
    renderUploadWrapper();
  }
  function renderUploadWrapper() {
    const observer=new MutationObserver(()=>{
      const form=$("#optionsForm");
      if(form&&!form.dataset.bound){
        form.dataset.bound="true";form.addEventListener("submit",handleNormalize);
        $("#backToMapping").addEventListener("click",()=>{state.confirmation=null;renderUpload();});
      }
    });
    observer.observe($("#mainContent"),{childList:true,subtree:true});
  }
  init();
})();