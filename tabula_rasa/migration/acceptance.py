"""Public, value-free rendering of whole-profile sign-off evidence."""

from collections import defaultdict


def acceptance_text(report):
    lines = ["Whole-profile migration acceptance: " + ("PASS" if report["passed"] else "FAIL"),
             "Source contract: #261 / PR #263, frozen format 13",
             "Run: " + report["run_id"], "Source digest: " + report["source_snapshot_sha256"],
             "Complete entity export: " + ("PASS" if report.get("export_verified") else "FAIL")]
    domains = defaultdict(list)
    for item in report["exceptions"]:
        domains[item["domain"]].append(item)
    if not domains:
        lines.append("Every supported migration unit, relationship and report comparison passed.")
    for domain in sorted(domains):
        lines.append(domain + ":")
        for item in sorted(domains[domain], key=lambda row: row.get("record_key", "")):
            lines.append("  " + item.get("record_key", "domain") + ": " + ", ".join(item["fields"]))
    lines.append("Authority switch requires the separate cutover gates.")
    return "\n".join(lines)
