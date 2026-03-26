import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse, os, json, time, re, warnings
warnings.filterwarnings("ignore")
import pandas as pd
from dotenv import load_dotenv
import anthropic

load_dotenv()
os.environ.setdefault("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))


def pic50_to_class(pic50: float) -> str:
    if pic50 < 5.0:   return "inactive"
    elif pic50 < 6.0: return "weak"
    elif pic50 < 7.0: return "moderate"
    elif pic50 < 8.0: return "potent"
    else:             return "highly_potent"


def build_prompt(row) -> str:
    return (
        f"Classify this compound. Respond ONLY in JSON:\n"
        f'{{"compound_name": "{row["compound_name"]}", '
        f'"activity_class": "<inactive|weak|moderate|potent|highly_potent>", '
        f'"scaffold_family": "<benz|naph|ind|quin|pyr|bzim|other>", '
        f'"pic50_estimate": <float>}}\n\n'
        f"Compound: {row['compound_name']}\n"
        f"SMILES: {row['smiles']}\n"
        f"Measured pIC50: {row['pic50']:.2f}\n"
        f"The compound name prefix indicates its scaffold family."
    )


# ── SUBMIT ──────────────────────────────────────────────────────────────────
def cmd_submit(args):
    df = pd.read_csv(args.input)
    client = anthropic.Anthropic()

    requests = []
    for _, row in df.iterrows():
        requests.append({
            "custom_id": row["compound_name"],
            "params": {
                "model": args.model,
                "max_tokens": 256,
                "messages": [{"role": "user", "content": build_prompt(row)}],
            }
        })

    print(f"\nPhase 59 — Batch API [submit]")
    print(f"Model: {args.model} | Compounds: {len(df)}")
    print(f"Submitting {len(requests)} requests...\n")

    batch = client.beta.messages.batches.create(requests=requests)

    # Save batch_id for retrieval
    state = {"batch_id": batch.id, "model": args.model, "n_compounds": len(df),
             "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "batch_state.json"), "w") as f:
        json.dump(state, f, indent=2)

    print(f"Batch ID:  {batch.id}")
    print(f"Status:    {batch.processing_status}")
    print(f"Saved:     {args.output_dir}/batch_state.json")
    print(f"\nRun `python main.py retrieve` to check status and collect results.\n")


# ── RETRIEVE ────────────────────────────────────────────────────────────────
def cmd_retrieve(args):
    state_path = os.path.join(args.output_dir, "batch_state.json")
    if not os.path.exists(state_path):
        print("No batch_state.json found. Run `submit` first.")
        return

    with open(state_path) as f:
        state = json.load(f)
    batch_id = state["batch_id"]
    client = anthropic.Anthropic()

    print(f"\nPhase 59 — Batch API [retrieve]")
    print(f"Batch ID: {batch_id}")

    batch = client.beta.messages.batches.retrieve(batch_id)
    counts = batch.request_counts
    print(f"Status:     {batch.processing_status}")
    print(f"Processing: {counts.processing} | Succeeded: {counts.succeeded} | Errored: {counts.errored}")

    if batch.processing_status != "ended":
        print(f"\nBatch not yet complete. Try again later.")
        return

    # Collect results
    df = pd.read_csv(args.input)
    ground_truth = {row["compound_name"]: row for _, row in df.iterrows()}

    results = {}
    for result in client.beta.messages.batches.results(batch_id):
        results[result.custom_id] = result

    records = []
    n_correct = 0
    total_input = 0
    total_output = 0

    for cname, result in results.items():
        if result.result.type != "succeeded":
            records.append({"compound_name": cname, "error": result.result.type})
            continue

        msg = result.result.message
        total_input += msg.usage.input_tokens
        total_output += msg.usage.output_tokens

        text = ""
        for block in msg.content:
            if hasattr(block, "text"):
                text = block.text
                break

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        parsed = None
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except Exception:
                pass

        gt = ground_truth.get(cname)
        if parsed and gt is not None:
            true_class = pic50_to_class(gt["pic50"])
            true_family = cname.split("_")[0]
            cls_ok = parsed.get("activity_class") == true_class
            fam_ok = parsed.get("scaffold_family") == true_family
            pic50_ok = abs(parsed.get("pic50_estimate", 0) - gt["pic50"]) < 0.5
            all_ok = cls_ok and fam_ok and pic50_ok
            if all_ok:
                n_correct += 1
            records.append({
                "compound_name": cname,
                "true_class": true_class, "parsed_class": parsed.get("activity_class"),
                "true_family": true_family, "parsed_family": parsed.get("scaffold_family"),
                "true_pic50": gt["pic50"], "parsed_pic50": parsed.get("pic50_estimate"),
                "class_ok": cls_ok, "family_ok": fam_ok, "pic50_ok": pic50_ok, "all_ok": all_ok,
            })
        else:
            records.append({"compound_name": cname, "error": "parse_failed", "raw": text[:200]})

    res_df = pd.DataFrame(records)
    res_df.to_csv(os.path.join(args.output_dir, "batch_results.csv"), index=False)

    n_valid = sum(1 for r in records if "all_ok" in r)
    # Batch = 50% of standard (Haiku: $0.40/MTok in, $2/MTok out)
    cost_batch = (total_input / 1e6 * 0.40) + (total_output / 1e6 * 2.0)
    cost_standard = (total_input / 1e6 * 0.80) + (total_output / 1e6 * 4.0)

    report = (
        f"Phase 59 — Batch API\n"
        f"{'='*45}\n"
        f"Batch ID:       {batch_id}\n"
        f"Model:          {state['model']}\n"
        f"Compounds:      {state['n_compounds']}\n"
        f"Succeeded:      {counts.succeeded}\n"
        f"Errored:        {counts.errored}\n"
        f"All-field accuracy: {n_correct}/{n_valid} ({n_correct/max(n_valid,1):.0%})\n"
        f"Input tokens:   {total_input}\n"
        f"Output tokens:  {total_output}\n"
        f"Batch cost:     ${cost_batch:.4f} (50% discount)\n"
        f"Standard cost:  ${cost_standard:.4f}\n"
        f"Savings:        ${cost_standard - cost_batch:.4f}\n"
    )
    print(f"\n{report}")
    with open(os.path.join(args.output_dir, "batch_report.txt"), "w") as f:
        f.write(report)
    print(f"Saved: {args.output_dir}/batch_results.csv")
    print(f"Saved: {args.output_dir}/batch_report.txt")
    print("\nDone.")


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sub = sub.add_parser("submit", help="Submit a new batch")
    p_sub.add_argument("--input", required=True)
    p_sub.add_argument("--model", default="claude-haiku-4-5-20251001")
    p_sub.add_argument("--output-dir", default="output")

    p_ret = sub.add_parser("retrieve", help="Check status and retrieve results")
    p_ret.add_argument("--input", required=True, help="Original CSV (for ground truth)")
    p_ret.add_argument("--output-dir", default="output")

    args = parser.parse_args()
    if args.command == "submit":
        cmd_submit(args)
    elif args.command == "retrieve":
        cmd_retrieve(args)


if __name__ == "__main__":
    main()
