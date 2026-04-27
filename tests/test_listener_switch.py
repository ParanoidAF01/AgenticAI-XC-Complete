"""
Test: Listener Switchability via API.

Demonstrates that the listener mode can be switched between ADF and SQL
while the backend is running, without restarting the server.

Prerequisites:
    - FastAPI backend running: python3 -m uvicorn backend.main:app --port 8000 --reload

Usage:
    python3 tests/test_listener_switch.py
"""
import requests
import time
import sys

BASE_URL = "http://127.0.0.1:8000"
PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def test(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, condition))
    print(f"  {status}  {name}" + (f" — {detail}" if detail else ""))
    return condition


def api_get(path):
    try:
        r = requests.get(f"{BASE_URL}{path}", timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def api_post(path, body=None):
    try:
        r = requests.post(f"{BASE_URL}{path}", json=body or {}, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("TEST: Listener Switchability via Backend API")
    print("=" * 60)

    # ── Step 0: Verify backend is running ────────────────────
    print("\n[Step 0] Verifying backend is running...")
    health = api_get("/api/health")
    if not test("Backend is healthy", health.get("status") == "healthy", str(health)):
        print("\n  ⚠️  Backend not running. Start it first:")
        print("  python3 -m uvicorn backend.main:app --port 8000 --reload\n")
        sys.exit(1)

    # ── Step 1: Check initial status ─────────────────────────
    print("\n[Step 1] Checking initial listener status...")
    status = api_get("/api/listener/status")
    test("Status endpoint returns data", "mode" in status, str(status))
    test("Listener is NOT running initially", status.get("running") == False)
    test("Available modes include 'adf' and 'sql'",
         set(status.get("available_modes", [])) == {"adf", "sql"},
         str(status.get("available_modes")))
    initial_mode = status.get("mode", "sql")
    print(f"    Initial mode: {initial_mode}")

    # ── Step 2: Start listener in SQL mode ───────────────────
    print("\n[Step 2] Starting listener in SQL mode...")
    start_result = api_post("/api/listener/start", {"mode": "sql"})
    # It might error due to missing pyodbc/connection, but status should update
    started_or_errored = start_result.get("status") in ("started", "error")
    test("Start endpoint responds", started_or_errored, str(start_result))

    if start_result.get("status") == "started":
        test("Mode is 'sql'", start_result.get("mode") == "sql")

        time.sleep(1)
        status = api_get("/api/listener/status")
        test("Listener is running", status.get("running") == True)
        test("Mode confirmed as 'sql'", status.get("mode") == "sql")
        test("Label is 'SQL Table Listener'", status.get("label") == "SQL Table Listener")
    else:
        print(f"    ⚠️  SQL listener can't start (expected without DB): {start_result.get('message', '')}")
        print(f"    Skipping running checks, testing mode switch logic...")

    # ── Step 3: Switch to ADF mode (restart) ─────────────────
    print("\n[Step 3] Switching to ADF mode via restart...")
    restart_result = api_post("/api/listener/restart", {"mode": "adf"})
    test("Restart endpoint responds", "status" in restart_result, str(restart_result))

    time.sleep(2)
    status = api_get("/api/listener/status")
    test("Mode switched to 'adf'", status.get("mode") == "adf",
         f"mode={status.get('mode')}")
    test("Label updated to 'ADF SDK Listener'",
         status.get("label") == "ADF SDK Listener",
         f"label={status.get('label')}")

    if status.get("running"):
        print("    Listener running in ADF mode ✓")

    # ── Step 4: Verify double-start protection ───────────────
    print("\n[Step 4] Testing double-start protection...")
    if status.get("running"):
        double_start = api_post("/api/listener/start", {"mode": "adf"})
        test("Double-start returns 'already_running'",
             double_start.get("status") == "already_running",
             str(double_start))
    else:
        print("    Skipped (listener not actively running)")

    # ── Step 5: Stop listener ────────────────────────────────
    print("\n[Step 5] Stopping listener...")
    stop_result = api_post("/api/listener/stop")
    test("Stop endpoint responds",
         stop_result.get("status") in ("stopped", "not_running"),
         str(stop_result))

    time.sleep(1)
    status = api_get("/api/listener/status")
    test("Listener is stopped", status.get("running") == False)

    # ── Step 6: Verify mode persisted after stop ─────────────
    print("\n[Step 6] Verifying mode persists after stop...")
    test("Mode still 'adf' after stop", status.get("mode") == "adf",
         f"mode={status.get('mode')}")

    # ── Step 7: Switch back to SQL and start ─────────────────
    print("\n[Step 7] Switching back to SQL mode...")
    restart_sql = api_post("/api/listener/restart", {"mode": "sql"})
    test("Restart to SQL responds", "status" in restart_sql, str(restart_sql))

    time.sleep(1)
    status = api_get("/api/listener/status")
    test("Mode switched back to 'sql'", status.get("mode") == "sql")

    # ── Step 8: Invalid mode test ────────────────────────────
    print("\n[Step 8] Testing invalid mode rejection...")
    invalid = api_post("/api/listener/start", {"mode": "databricks"})
    test("Invalid mode returns error", invalid.get("status") == "error",
         str(invalid))

    # ── Cleanup: Stop everything ─────────────────────────────
    print("\n[Cleanup] Stopping listener...")
    api_post("/api/listener/stop")

    # ── Summary ──────────────────────────────────────────────
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\n🎉 All tests passed! Listener is fully switchable via API.\n")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Check output above.\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
