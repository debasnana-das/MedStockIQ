# Data readiness matrix

| Analysis | Required evidence | If missing |
|---|---|---|
| Overstock | Current stock, dated demand history, units, and an explicit inventory target or labelled assumption; incoming stock improves the estimate | Report missing inputs; do not claim a reliable forecast-based result |
| Expiry calendar alert | Usable batch expiry date | Ask user to confirm expiry parsing or mark unmapped |
| Predicted expiry loss | Batch expiry, current remaining batch quantity, demand history/forecast and consistent units | Show calendar alert only or return insufficient data for unsold-quantity prediction |
| Stock-out | Current stock, dated demand history, lead time and pending/incoming receipts where available | Defer reliable prediction until replenishment inputs are available |

Invoice purchase/distribution records describe stock movements between business entities. A stockist's dispatches to retailers are not the same as a pharmacy's sales to patients. Current stock cannot be inferred from one invoice alone.

