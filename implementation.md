# Phase 59 — Batch API: 100 Compounds Async at 50% Cost

**Version:** 1.0 | **Tier:** Standard | **Date:** 2026-03-26

## Goal
Demonstrate the Anthropic Batch API to process all 45 compounds asynchronously at 50% cost reduction.
Each compound gets a SAR classification request submitted as a batch, then results are polled/retrieved.

CLI: `python main.py --input data/compounds.csv --model claude-haiku-4-5-20251001`

Outputs: batch_results.csv, batch_report.txt

## Logic
- Load all compounds from CSV
- Build one request per compound (custom_id = compound_name, content = SAR prompt)
- Submit batch via `client.beta.messages.batches.create(requests=[...])`
- Poll batch status until `processing_status == "ended"` (or load from results if already done)
- Iterate results via `client.beta.messages.batches.results(batch_id)`
- Parse response per compound, validate against ground truth
- Report: batch_id, processing time, accuracy, token usage, cost comparison (batch vs standard)

## Key Concepts
- `client.beta.messages.batches.create(requests=[...])` submits a batch
- Each request: `{"custom_id": str, "params": {"model": ..., "max_tokens": ..., "messages": [...]}}`
- Batch processes asynchronously (up to 24h); typically minutes for small batches
- `client.beta.messages.batches.retrieve(batch_id)` to check status
- `client.beta.messages.batches.results(batch_id)` streams results when done
- Result types: `"succeeded"`, `"errored"`, `"canceled"`, `"expired"`
- Cost: 50% of standard API pricing

## Pydantic Schema
```python
class CompoundClassification(BaseModel):
    compound_name: str
    activity_class: Literal["inactive", "weak", "moderate", "potent", "highly_potent"]
    scaffold_family: Literal["benz", "naph", "ind", "quin", "pyr", "bzim", "other"]
    pic50_estimate: float
```

## Verification Checklist
- [ ] Batch created and batch_id returned
- [ ] Status polling shows ended
- [ ] Results iterated without errors
- [ ] Accuracy reported vs ground truth
- [ ] Cost comparison shown

## Risks
- Batch API may timeout waiting; add --wait flag to control polling duration
- Small batches (45) may complete quickly; demonstrate the pattern regardless
