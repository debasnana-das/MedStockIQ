# Data readiness matrix

| Analysis | Required evidence | If missing |
|---|---|---|
| Overstock | Current stock, dated demand history, consistent units, incoming stock where available, and an explicit inventory target or a clearly labelled assumption | Report missing inputs; do not claim a reliable forecast-based result |
| Expiry calendar alert | Usable batch expiry date | Ask user to confirm expiry parsing or mark it unmapped |
| Predicted expiry loss | Batch expiry, remaining batch quantity, demand history/forecast and consistent units | Show a calendar alert only or return insufficient data for unsold-quantity prediction |
| Stock-out | Current stock, dated demand history, lead time and incoming receipts where available | Defer reliable prediction until replenishment inputs are available |

Purchase/distribution invoices describe stock movements between business entities. Stockist dispatches to retailers are not the same as a pharmacy's sales to patients. Current stock cannot be inferred from a single invoice alone.

## Synthetic testing

Use synthetic ground-truth files only to test controlled scenarios and arithmetic. Do not include them as input features. Real-world performance claims require validation against authorized real data.
