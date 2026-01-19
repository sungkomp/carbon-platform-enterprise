"""Produce ChatGPT-ready output from the demo workflow.

This script reuses the demo SQLite workflow runner to emit concise JSON that
can be pasted into a ChatGPT conversation as context or evidence. It prints a
summary plus the raw payloads/responses so LLMs can ground answers in data
without needing to start the full web UI.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_sample_workflow import run_workflow


def format_for_chatgpt(result: dict) -> str:
    """Return a ChatGPT-friendly summary string for the workflow result."""
    lines = [
        "Demo workflow completed successfully.",
        f"Database: {Path(result['db_path']).resolve()}",
        "Emission factor:",
        f"  key={result['ef_response']['key']} value={result['ef_payload']['value']} unit={result['ef_payload']['unit']}",
        "Activity:",
        f"  id={result['activity_response']['id']} name={result['activity_payload']['name']} inputs={result['activity_payload']['inputs']}",
        "Run totals:",
        f"  kgCO2e={result['run_response']['total_kgco2e']} tCO2e={result['run_response']['total_tco2e']}",
        "Dashboard counts:",
        f"  activities={result['dashboard']['counts']['activities']} runs={result['dashboard']['counts']['runs']}",
    ]
    return "\n".join(lines)


def main():
    result = run_workflow()

    chatgpt_text = format_for_chatgpt(result)
    print("=== ChatGPT summary ===")
    print(chatgpt_text)
    print()

    print("=== Raw payloads/responses (JSON) ===")
    print(
        json.dumps(
            {
                "ef_payload": result["ef_payload"],
                "ef_response": result["ef_response"],
                "activity_payload": result["activity_payload"],
                "activity_response": result["activity_response"],
                "run_response": result["run_response"],
                "dashboard": result["dashboard"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
