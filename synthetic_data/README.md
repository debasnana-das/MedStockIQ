# Source-shaped synthetic demo inputs

Use `python -m synthetic_data.generate_demo_inputs --output-dir data/demo-inputs --seed 42` to produce fictional CSVs that resemble pharmacy retail-sales, batch-inventory and purchase-invoice exports. The output is reproducible for a fixed seed and as-of date.

The output directory contains source uploads and a manifest only. The generator creates its internal simulation in a temporary directory; evaluation truth and scenario labels are not copied into the demo inputs.

For profile → confirm → normalize/save → expiry/demand → inventory-history → overstock-review, see [the demo workflow](../docs/synthetic_demo.md).
