import subprocess
import sys
import time

print("Starting diagnostic run to capture failure details...")
for i in range(1, 11):
    t0 = time.perf_counter()
    res = subprocess.run([sys.executable, "verify_e2e.py"], capture_output=True, text=True)
    dt = time.perf_counter() - t0
    print(f"Run {i}: exit={res.returncode}, duration={dt:.2f}s")
    if res.returncode != 0:
        print("=" * 80)
        print(f"FAILURE CAPTURED ON RUN {i}:")
        print("STDOUT:")
        print(res.stdout)
        print("STDERR:")
        print(res.stderr)
        print("=" * 80)
        break
