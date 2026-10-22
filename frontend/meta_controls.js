(() => {
  "use strict";
  // Enable month-end expiry convention only when the confirmed format is month/year.
  document.addEventListener("change", event => {
    const format = event.target;
    if (!format.matches('[data-role="meta"][data-meta="date_format"]')) return;
    const row = format.closest("[data-schema-row]");
    if (!row) return;
    const target = row.querySelector('[data-role="meta"][data-meta="date_convention"]');
    const canonical = row.querySelector('[data-role="canonical"]');
    if (!target || !canonical) return;
    const enabled = !canonical.disabled && canonical.value === "expiry_date" && ["MM/YY", "MM/YYYY"].includes(format.value);
    target.disabled = !enabled;
    if (!enabled) target.value = "";
  });
})();