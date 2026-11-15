"""
verify_e2e.py — Comprehensive 4-Tier Automated Verification Suite Runner.

Project: AssetDrop — Cross-Device Media Ingestion Engine (v2.0)
Architecture: Headless Windows Service + Mobile PWA Client + Subprocess Ingestion Matrix

Discovers and executes:
- Tier 1: Feature Isolation Verification (Features 1 - 28) [tests/test_tier1_features.py]
- Tier 2: Boundary Value & Adversarial Corner Cases [tests/test_tier2_boundaries.py]
- Tier 3: Cross-Feature Combinations & Load Bursts [tests/test_tier3_combinations.py]
- Tier 4: Real-World Operational Workflows [tests/test_tier4_workflows.py]

Zero external dependencies: uses Python standard library unittest and Starlette TestClient.
Exit code: 0 on 100% pass, 1 on any failure.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import unittest

# Silence overly verbose third-party loggers during test runner execution
logging.basicConfig(level=logging.WARNING)
for log_name in ("assetdrop", "httpx", "httpx2", "httpcore"):
    logging.getLogger(log_name).setLevel(logging.WARNING)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


TIER_SPECS = [
    {
        "tier": "Tier 1",
        "name": "Feature Isolation & Architecture Contracts",
        "module": "tests.test_tier1_features",
        "threshold": 28,
        "description": "Happy-path isolation verification of core features, UID derivation, and UI contracts",
    },
    {
        "tier": "Tier 2",
        "name": "Boundary Values, Security Limits & Adversarial Corner Cases",
        "module": "tests.test_tier2_boundaries",
        "threshold": 28,
        "description": "Malformed inputs, command injection defenses, UID/password boundaries, SSRF, path containment",
    },
    {
        "tier": "Tier 3",
        "name": "Cross-Feature Combinations & Concurrency",
        "module": "tests.test_tier3_combinations",
        "threshold": 10,
        "description": "10-request bursts (<50ms SLA), multi-platform batches, concurrent auth sessions, telemetry polling",
    },
    {
        "tier": "Tier 4",
        "name": "Real-World Operational Workflows",
        "module": "tests.test_tier4_workflows",
        "threshold": 7,
        "description": "End-to-end NLE workflows, B-Roll, SFX, Social, Pinterest, Windows lifecycle, full mobile auth lifecycle",
    },
]


def print_banner(text: str, char: str = "=", width: int = 80):
    print(char * width)
    print(f" {text}")
    print(char * width)


def run_verification_suite() -> int:
    start_total = time.perf_counter()

    print("\n" + "=" * 80)
    print("  ASSETDROP (v2.0) — 4-TIER AUTOMATED VERIFICATION SUITE")
    print("  Host: Windows Workstation (x64) | Headless Daemon: Port 8000")
    print("=" * 80)

    from core.config import DEFAULT_PRESETS, load_config, save_config
    user_config_backup = load_config()
    test_cfg = dict(user_config_backup)
    test_presets = dict(DEFAULT_PRESETS)
    test_presets.update(test_cfg.get("presets", {}))
    test_cfg["presets"] = test_presets
    save_config(test_cfg)

    try:
        loader = unittest.TestLoader()
        total_run = 0
        total_passed = 0
        total_failed = 0
        total_errors = 0
        tier_results = []

        for spec in TIER_SPECS:
            tier_title = f"{spec['tier']}: {spec['name']}"
            print(f"\n>>> Running {tier_title}...")
            print(f"    Scope: {spec['description']}")
            print(f"    Required minimum test count: >= {spec['threshold']}")

            try:
                suite = loader.loadTestsFromName(spec["module"])
            except Exception as exc:
                print(f"    [ERROR] Failed to load module {spec['module']}: {exc}")
                return 1

            runner = unittest.TextTestRunner(
                verbosity=1,
                failfast=False,
                stream=sys.stdout,
            )

            t0 = time.perf_counter()
            result = runner.run(suite)
            elapsed = time.perf_counter() - t0

            run_count = result.testsRun
            fail_count = len(result.failures)
            err_count = len(result.errors)
            pass_count = run_count - (fail_count + err_count)

            total_run += run_count
            total_passed += pass_count
            total_failed += fail_count
            total_errors += err_count

            status = "PASSED" if (fail_count == 0 and err_count == 0 and run_count >= spec["threshold"]) else "FAILED"

            tier_results.append({
                "tier": spec["tier"],
                "name": spec["name"],
                "run": run_count,
                "passed": pass_count,
                "failed": fail_count,
                "errors": err_count,
                "threshold": spec["threshold"],
                "elapsed": elapsed,
                "status": status,
            })

            print(f"    Result: {status} ({pass_count}/{run_count} passed, {elapsed:.2f}s)")
            if run_count < spec["threshold"]:
                print(f"    [WARNING] Test count {run_count} below threshold >= {spec['threshold']}")

            # Quiesce background thread pools and clear queue state between tiers
            try:
                from core.queue_manager import get_queue_manager
                qm = get_queue_manager()
                t_wait = 0.0
                while qm._active and t_wait < 0.2:
                    time.sleep(0.02)
                    t_wait += 0.02
                qm.clear_history()
                import gc
                gc.collect()
                time.sleep(0.05)
            except Exception:
                pass
    finally:
        save_config(user_config_backup)

    total_elapsed = time.perf_counter() - start_total

    # Summary Table
    print("\n" + "=" * 80)
    print("  AUTOMATED VERIFICATION SUMMARY REPORT")
    print("=" * 80)
    print(f" {'Tier':<8} | {'Name':<42} | {'Req':<4} | {'Run':<4} | {'Pass':<4} | {'Status':<6}")
    print("-" * 80)

    all_passed = True
    for tr in tier_results:
        print(
            f" {tr['tier']:<8} | {tr['name'][:42]:<42} | "
            f">={tr['threshold']:<2} | {tr['run']:<4} | {tr['passed']:<4} | {tr['status']:<6}"
        )
        if tr["status"] != "PASSED":
            all_passed = False

    print("-" * 80)
    print(
        f" {'TOTAL':<8} | {'All 4 Tiers Verified':<42} | "
        f">=73 | {total_run:<4} | {total_passed:<4} | {'PASSED' if all_passed else 'FAILED':<6}"
    )
    print(f"\nExecution Duration: {total_elapsed:.2f} seconds")
    print("=" * 80)

    if all_passed and total_run >= 73:
        print("  [SUCCESS] 100% of E2E verification test cases passed successfully.")
        print("  AssetDrop v2.0 is fully verified and ready for production deployment.")
        print("=" * 80 + "\n")
        return 0
    else:
        print(f"  [FAILURE] Verification encountered {total_failed} failures and {total_errors} errors.")
        print("=" * 80 + "\n")
        return 1


if __name__ == "__main__":
    exit_code = run_verification_suite()
    sys.exit(exit_code)
