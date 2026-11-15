import os
import subprocess
import sys
import time

log_dir = os.path.join(os.path.dirname(__file__), "run_logs")
os.makedirs(log_dir, exist_ok=True)

results = []
durations = []

print("Running 10 consecutive runs of verify_e2e.py with per-run log persistence...")

for i in range(1, 11):
    log_file = os.path.join(log_dir, f"verify_run_{i}.log")
    t0 = time.perf_counter()
    res = subprocess.run([sys.executable, "verify_e2e.py"], capture_output=True, text=True)
    dt = time.perf_counter() - t0

    results.append(res.returncode)
    durations.append(round(dt, 2))

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"EXIT CODE: {res.returncode}\n")
        f.write(f"DURATION: {dt:.2f}s\n\n")
        f.write("=== STDOUT ===\n")
        f.write(res.stdout)
        f.write("\n=== STDERR ===\n")
        f.write(res.stderr)

    status_str = "PASS" if res.returncode == 0 else f"FAIL (exit {res.returncode})"
    print(f"Run {i:02d}/10: exit={res.returncode} ({status_str}), duration={dt:5.2f}s")

    if res.returncode != 0:
        print(f"  --> Failure logged to {log_file}")
        # Print fail snippet
        for line in res.stdout.splitlines():
            if "FAIL:" in line or "ERROR:" in line or "FAILED" in line or "AssertionError" in line:
                print(f"      {line}")
        for line in res.stderr.splitlines():
            if "FAIL:" in line or "ERROR:" in line or "FAILED" in line or "AssertionError" in line:
                print(f"      {line}")

print("-" * 80)
print(f"Results: {results}")
print(f"Durations: {durations}")
sys.exit(0 if all(r == 0 for r in results) else 1)
