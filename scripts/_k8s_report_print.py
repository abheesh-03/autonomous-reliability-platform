"""Phase 12A: prints the Kubernetes collection/finding summary from a
`python -m detectors analyze` JSON report. Kept as a standalone file
(rather than an inline `python3 -c "..."` string) so
scripts/verify-kubernetes-observer-real-stack.sh never needs to nest
Python source inside shell quoting -- see that script's own Issue 5
correction-round comment for why inline interpolation was removed."""

import json
import sys

report = json.load(open(sys.argv[1]))

for cr in report["k8s_collection_results"]:
    print(f"  collection: {cr['resource_kind']:<12} outcome={cr['outcome']:<10} detail={cr['detail']}")

print(f"  {len(report['k8s_findings'])} Kubernetes finding(s) (0 is a valid, honest result for a healthy cluster)")
for f in report["k8s_findings"]:
    print(f"    - {f['detector_id']}: {f['resource_kind']}/{f['namespace']}/{f['resource_name']} -> {f['result']}")
