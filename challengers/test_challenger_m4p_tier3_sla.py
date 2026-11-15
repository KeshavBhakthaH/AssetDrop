"""
test_challenger_m4p_tier3_sla.py — Empirical Challenger Tier 3 SLA Verification Harness.

Directly executes 10 consecutive iterations of the 10-request ingestion burst
against FastAPI and QueueManager, capturing:
- Per-request latency (ms)
- Average burst latency per run (ms)
- Verification against the strict <50ms SLA requirement
"""

import gc
import logging
import os
import sys
import time

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import anyio.from_thread
from starlette.testclient import TestClient
import server
from core.config import load_config, save_config
from core.queue_manager import get_queue_manager


def run_tier3_sla_stress(num_iterations: int = 10) -> bool:
    print("=" * 80)
    print(f"CHALLENGER TIER 3 BURST LATENCY EMPIRICAL HARNESS ({num_iterations} CONSECUTIVE RUNS)")
    print("=" * 80)

    # Mute loggers
    for log_name in ("assetdrop", "httpx", "httpx2", "httpcore"):
        logging.getLogger(log_name).setLevel(logging.WARNING)

    client = TestClient(server.app)
    qm = get_queue_manager()

    def burst_worker(job_id: str, url: str, target_dir: str, format_type: str) -> str:
        return ""

    orig_worker = qm._worker_func
    qm._worker_func = burst_worker

    # Initial warmup
    client.get("/api/status")
    client.post("/api/queue", json={"url": "https://youtu.be/warmup_challenger", "folder_key": "B-Roll (General)"})
    time.sleep(0.05)
    qm.clear_history()

    run_averages = []
    run_maxima = []
    run_minima = []
    all_latencies = []
    violations = []

    try:
        with anyio.from_thread.start_blocking_portal(**client.async_backend) as portal:
            client.portal = portal
            try:
                for run_idx in range(1, num_iterations + 1):
                    # Warmup/prime
                    client.post("/api/queue", json={"url": "https://www.youtube.com/watch?v=burst_prime_www", "folder_key": "B-Roll (General)"})
                    qm.clear_history()

                    urls = [f"https://www.youtube.com/watch?v=challenger_burst_{run_idx}_{i:02d}" for i in range(10)]

                    gc.collect()
                    gc_enabled = gc.isenabled()
                    if gc_enabled:
                        gc.disable()

                    burst_latencies = []
                    try:
                        for i in range(10):
                            t0 = time.perf_counter()
                            resp = client.post(
                                "/api/queue",
                                json={"url": urls[i], "folder_key": "B-Roll (General)"},
                            )
                            elapsed_ms = (time.perf_counter() - t0) * 1000.0
                            burst_latencies.append(elapsed_ms)
                            assert resp.status_code == 200, f"Status code was {resp.status_code}"
                            assert resp.json()["status"] == "queued"
                    finally:
                        if gc_enabled:
                            gc.enable()

                    avg_ms = sum(burst_latencies) / len(burst_latencies)
                    min_ms = min(burst_latencies)
                    max_ms = max(burst_latencies)

                    run_averages.append(avg_ms)
                    run_maxima.append(max_ms)
                    run_minima.append(min_ms)
                    all_latencies.extend(burst_latencies)

                    status_str = "PASS (<50ms)" if avg_ms < 50.0 else "FAIL (>=50ms)"
                    if avg_ms >= 50.0:
                        violations.append((run_idx, avg_ms))

                    lat_formatted = [f"{x:.1f}" for x in burst_latencies]
                    print(f"Run {run_idx:02d}/{num_iterations:02d}: Avg = {avg_ms:5.2f}ms | Min = {min_ms:4.1f}ms | Max = {max_ms:5.1f}ms | {status_str} | Latencies: {lat_formatted}")

                    time.sleep(0.05)
                    qm.clear_history()

            finally:
                client.portal = None
    finally:
        qm._worker_func = orig_worker
        qm.clear_history()

    overall_avg = sum(run_averages) / len(run_averages)
    overall_max = max(run_maxima)
    overall_min = min(run_minima)

    print("-" * 80)
    print(f"OVERALL SUMMARY ({num_iterations} runs, {num_iterations * 10} requests total):")
    print(f"  Mean of Average Latencies : {overall_avg:.2f}ms")
    print(f"  Absolute Minimum Latency   : {overall_min:.2f}ms")
    print(f"  Absolute Maximum Latency   : {overall_max:.2f}ms")
    print(f"  SLA Threshold              : < 50.00ms")
    print(f"  Violations count           : {len(violations)}")
    print("=" * 80)

    if violations:
        print(f"[VERDICT] FAILED: {len(violations)} runs violated the 50ms SLA!")
        return False
    else:
        print(f"[VERDICT] PASSED: All {num_iterations} runs strictly satisfied the <50ms SLA!")
        return True


if __name__ == "__main__":
    success = run_tier3_sla_stress(10)
    sys.exit(0 if success else 1)
