"""Phase 7 Scaling Readiness Gate Test Runner.

Runs:
- Load Test Suite (`tests/load/test_load_scaling.py`)
- Chaos Resilience Test Suite (`tests/chaos/test_chaos_resilience.py`)
- Security Pen-Test Suite (`tests/security/test_security_pentest.py`)

Summarizes performance against the 5 Definition of Done Scaling Readiness Criteria:
1. p95 context-aggregation latency < 60s
2. Zero orphaned incidents after chaos scenarios
3. Provider failover confirmed working under load
4. Queue depth stays bounded (peak <= 50, drains < 30s)
5. Security pen-test (100+ prompt injection payloads, IAM escalation) zero unresolved critical findings
"""

import sys
import time
import pytest


def run_phase7_readiness_evaluation():
    print("=" * 80)
    print(" RISE — Phase 7 Scaling Readiness Gate Execution ")
    print("=" * 80)
    start_time = time.time()

    # 1. Run Load Test Suite
    print("\n--- Running Load & Scaling Tests ---")
    load_exit = pytest.main(["-v", "tests/load/test_load_scaling.py"])

    # 2. Run Chaos Resilience Suite
    print("\n--- Running Chaos Resilience Tests ---")
    chaos_exit = pytest.main(["-v", "tests/chaos/test_chaos_resilience.py"])

    # 3. Run Security Pen-Test Suite
    print("\n--- Running Security Pen-Tests ---")
    security_exit = pytest.main(["-v", "tests/security/test_security_pentest.py"])

    total_time = time.time() - start_time

    print("\n" + "=" * 80)
    print(" SUMMARY OF PHASE 7 DEFINITION OF DONE GATES ")
    print("=" * 80)
    
    gates = [
        ("p95 Context Aggregation Latency < 60s", load_exit == 0),
        ("Zero Orphaned Incidents Post-Chaos", chaos_exit == 0),
        ("Provider Failover Under Load Confirmed", chaos_exit == 0),
        ("Queue Depth Bounded (Peak <= 50, Drain < 30s)", load_exit == 0),
        ("Security Pen-Test Zero Critical Findings", security_exit == 0),
    ]

    all_passed = True
    for name, passed in gates:
        status = "PASSED [OK]" if passed else "FAILED [FAIL]"
        if not passed:
            all_passed = False
        print(f"[{status}] {name}")

    print("-" * 80)
    print(f"Total Execution Time: {total_time:.2f} seconds")
    if all_passed:
        print("RESULT: ALL PHASE 7 SCALING READINESS GATES PASSED SUCCESSFULLY!")
    else:
        print("RESULT: ONE OR MORE SCALING READINESS GATES FAILED.")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_phase7_readiness_evaluation())
