#!/usr/bin/env python3
"""Acceptance checks for Practice 3 against the RUNNING stack (works on Windows/Linux/macOS).

Only the Python standard library is used (3.9+).

    docker compose up -d --build
    python scripts/verify.py                       # checks 1-10 + timing (experiment 1)
    python scripts/verify.py --with-docker         # + Forecast API stopped/started (experiments 2, 4)
    python scripts/verify.py --restart-experiment  # + orders-api restart while a task is pending (experiment 3)

The output is also written to logs/verify.log (paste it into REPORT.md).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, bool]] = []
TIMINGS: dict[str, float] = {}
BASE = "http://127.0.0.1:8000"
LOG_LINES: list[str] = []


def out(line=""):
    print(line)
    LOG_LINES.append(line)


def read_env_port() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ORDERS_PORT="):
                return line.split("=", 1)[1].strip()
    return "8000"


def call(method, path, body=None, token=None, form=None, timeout=90):
    data, headers = None, {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, hdrs, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        status, hdrs, raw = exc.code, exc.headers, exc.read()
    elapsed = time.perf_counter() - started
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode(errors="replace")
    return status, parsed, hdrs, elapsed


def check(name, condition, info=""):
    RESULTS.append((name, bool(condition)))
    out(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({info})" if info else ""))
    return bool(condition)


def wait_status(token, order_id, wanted, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, body, _, _ = call("GET", f"/orders/{order_id}", token=token)
        if isinstance(body, dict) and body.get("status") == wanted:
            return body
        time.sleep(0.3)
    return None


def wait_health(seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if call("GET", "/health", timeout=3)[0] == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def payload(i=0):
    return {
        "customer_name": f"Client {i}",
        "area_sqm": 60 + i * 5,
        "bedrooms": 1 + i % 4,
        "bathrooms": 1 + i % 3,
        "year_built": 1990 + i,
    }


def docker(*args, env=None):
    cmd = ["docker", "compose", *args]
    out("   $ " + " ".join(cmd))
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=ROOT, env=full_env, check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None)
    parser.add_argument("--limit", type=int, default=50, help="BATCH_MAX_ITEMS of the running stack")
    parser.add_argument("--with-docker", action="store_true")
    parser.add_argument("--restart-experiment", action="store_true")
    args = parser.parse_args()
    BASE = (args.base or f"http://127.0.0.1:{read_env_port()}").rstrip("/")

    out(f"=== Practice 3 verification {time.strftime('%Y-%m-%d %H:%M:%S')} against {BASE} ===")
    if not wait_health(30):
        out("Orders API is not reachable. Start the stack first: docker compose up -d --build")
        sys.exit(2)
    check("1. Docker Compose: Orders API is up (GET /health)", True)

    # forecast-api must not be published to the host
    try:
        urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=3)
        published = True
    except Exception:
        published = False
    check("Forecast API is NOT reachable from the host (port 8001 not published)", not published)

    # ---- authentication
    username, password = f"verify_{int(time.time())}", "Passw0rd-lab3-ok"
    status, _, _, _ = call("POST", "/auth/register", {"username": username, "password": password})
    check("Registration -> 201", status == 201, f"status={status}")
    status, body, _, _ = call("POST", "/auth/login", form={"username": username, "password": password})
    token = body.get("access_token") if isinstance(body, dict) else None
    check("Login (form) returns a JWT", status == 200 and bool(token))

    # ---- check 9: no token
    codes = (
        call("GET", "/orders")[0],
        call("POST", "/orders", payload())[0],
        call("POST", "/orders/batch", [payload()])[0],
        call("GET", "/orders", token="bad.token.value")[0],
    )
    check("9. Requests without / with a bad token -> 401", codes == (401, 401, 401, 401), str(codes))

    # ---- checks 2, 3: create -> 202 pending -> priced
    status, body, headers, elapsed = call("POST", "/orders", payload(0), token=token)
    ok = (status == 202 and isinstance(body, dict) and body.get("status") == "pending"
          and body.get("predicted_price") is None)
    check("2. POST /orders -> 202, status=pending, predicted_price=null", ok, f"status={status}, {elapsed:.2f}s")
    order_id = body["id"]
    check("2. Location header points to the order", headers.get("Location") == f"/orders/{order_id}", str(headers.get("Location")))
    TIMINGS["POST /orders (202), s"] = elapsed
    done = wait_status(token, order_id, "priced")
    check("3. After processing status becomes priced (price stored)", bool(done) and done.get("predicted_price") is not None,
          str(done and done.get("predicted_price")))
    price_before = done.get("predicted_price") if done else None

    # ---- check 4 + experiment 1: batch of 10 vs ten batches of 1
    status, body, _, t_batch = call("POST", "/orders/batch", [payload(i) for i in range(10)], token=token)
    results = body.get("results", []) if isinstance(body, dict) else []
    ok = status == 200 and body.get("total") == 10 and len(results) == 10 and all(r.get("status") == "priced" for r in results)
    check("4. Batch of 10 orders: a result for every element", ok, f"status={status}, {t_batch:.2f}s")
    t_seq = 0.0
    for i in range(10):
        t_seq += call("POST", "/orders/batch", [payload(i)], token=token)[3]
    TIMINGS["1 batch with 10 orders (concurrent), s"] = t_batch
    TIMINGS["10 batches with 1 order each (sequential), s"] = t_seq
    check("Exp.1: one concurrent batch of 10 is faster than 10 separate batches", t_batch < t_seq, f"{t_batch:.2f}s vs {t_seq:.2f}s")

    # ---- check 5: limit
    status = call("POST", "/orders/batch", [payload(i % 20) for i in range(args.limit + 1)], token=token)[0]
    check(f"5. Batch with {args.limit + 1} orders (> limit) -> 422", status == 422, f"status={status}")
    status = call("POST", "/orders/batch", [{"customer_name": "x"}], token=token)[0]
    check("Invalid element structure -> 422", status == 422, f"status={status}")

    # ---- check 7: PATCH property params
    status, body, _, _ = call("PATCH", f"/orders/{order_id}", {"area_sqm": 200, "bedrooms": 5}, token=token)
    check("7. PATCH of property parameters -> 202, pending, price cleared",
          status == 202 and body.get("status") == "pending" and body.get("predicted_price") is None, f"status={status}")
    done = wait_status(token, order_id, "priced")
    check("7. A new forecast is computed and differs from the old one",
          bool(done) and done.get("predicted_price") != price_before, str(done and done.get("predicted_price")))
    price_after = done.get("predicted_price") if done else None

    # ---- check 8: PATCH client data only
    status, body, _, _ = call("PATCH", f"/orders/{order_id}", {"customer_name": "Renamed", "order_status": "confirmed"}, token=token)
    time.sleep(0.5)
    current = call("GET", f"/orders/{order_id}", token=token)[1]
    check("8. PATCH of client data only: forecast is NOT recomputed",
          status == 200 and body.get("status") == "priced" and current.get("status") == "priced"
          and current.get("predicted_price") == price_after and current.get("customer_name") == "Renamed",
          f"status={status}")

    # ---- check 10 + experiment 4: rerun without duplicates
    count_before = len(call("GET", "/orders?limit=200", token=token)[1])
    status = call("POST", f"/orders/{order_id}/forecast", token=token)[0]
    done = wait_status(token, order_id, "priced")
    count_after = len(call("GET", "/orders?limit=200", token=token)[1])
    check("10. Re-running the task: no duplicates, state is correct",
          status == 202 and count_before == count_after and bool(done) and done.get("predicted_price") == price_after,
          f"orders before/after: {count_before}/{count_after}")

    # ---- order deleted while the task is in flight
    gone_id = call("POST", "/orders", payload(3), token=token)[1]["id"]
    call("DELETE", f"/orders/{gone_id}", token=token)
    time.sleep(2.5)
    events = call("GET", f"/events?order_id={gone_id}", token=token)[1]
    check("Order deleted during processing: task ended cleanly (event 'skipped')",
          isinstance(events, list) and any(e["result"] == "skipped" for e in events),
          str([e["result"] for e in events]) if isinstance(events, list) else "")
    events = call("GET", f"/events?order_id={order_id}", token=token)[1]
    check("Event log holds order id, result and timestamp",
          isinstance(events, list) and len(events) >= 3 and all(e.get("created_at") and e.get("result") for e in events),
          f"events: {len(events) if isinstance(events, list) else '?'}")

    # ---- experiments 2 / 4: Forecast API unavailable
    if args.with_docker:
        out("\n--- Forecast API unavailable ---")
        docker("stop", "forecast-api")
        time.sleep(1)
        status, body, _, elapsed = call("POST", "/orders", payload(5), token=token)
        down_id = body.get("id") if isinstance(body, dict) else None
        check("Exp.2: create while Forecast API is down -> 202 quickly", status == 202 and elapsed < 2, f"status={status}, {elapsed:.2f}s")
        TIMINGS["POST /orders with Forecast API down, s"] = elapsed
        failed = wait_status(token, down_id, "failed", timeout=15)
        check("Exp.2 / check 6: the order is saved with status failed", bool(failed))
        status, body, _, elapsed = call("POST", "/orders/batch", [payload(i) for i in range(3)], token=token)
        results = body.get("results", []) if isinstance(body, dict) else []
        check("Check 6: batch while the service is down - orders saved, per-item error",
              status == 200 and len(results) == 3 and all(r["status"] == "failed" and r.get("order_id") for r in results),
              f"{elapsed:.2f}s, error={results[0].get('error') if results else None}")
        docker("start", "forecast-api")
        out("   waiting for forecast-api ...")
        recovered = None
        for _ in range(25):
            time.sleep(2)
            call("POST", f"/orders/{down_id}/forecast", token=token)
            recovered = wait_status(token, down_id, "priced", timeout=5)
            if recovered:
                break
        check("Exp.3/4: after recovery a re-run turns the failed order into priced", bool(recovered))

    # ---- experiment 3: restart the component that runs the tasks (variant A: orders-api)
    if args.restart_experiment:
        out("\n--- Experiment 3: orders-api restarted while a task is pending ---")
        slow = {"FORECAST_DELAY_SEC": "30", "FORECAST_TIMEOUT": "60"}
        try:
            docker("up", "-d", "forecast-api", "orders-api", env=slow)
            if not check("   stack is up with a slow Forecast API", wait_health(90)):
                raise RuntimeError("orders-api did not come up")
            time.sleep(3)
            status, body, _, _ = call("POST", "/orders", payload(7), token=token)
            slow_id = body["id"]
            check("   order created, status pending", status == 202 and body["status"] == "pending")
            docker("restart", "orders-api")
            check("   orders-api is healthy again after the restart", wait_health(90))
            time.sleep(5)
            after = call("GET", f"/orders/{slow_id}", token=token)[1]
            check("   after the restart the order is STILL pending: variant A lost the task (expected)",
                  isinstance(after, dict) and after.get("status") == "pending", str(after and after.get("status")))
        finally:
            out("   restoring default settings ...")
            docker("up", "-d")
            wait_health(90)
        time.sleep(3)
        if "slow_id" in locals():
            call("POST", f"/orders/{slow_id}/forecast", token=token)
            check("   a manual re-run completes the lost order", bool(wait_status(token, slow_id, "priced", timeout=20)))

    # ---- summary
    out("\n=== TIMINGS (for the report) ===")
    out("| Scenario | Time |")
    out("|---|---|")
    for key, value in TIMINGS.items():
        out(f"| {key} | {value:.2f} |")
    failed_checks = [name for name, ok in RESULTS if not ok]
    out(f"\nSummary: {len(RESULTS) - len(failed_checks)}/{len(RESULTS)} checks passed")
    for name in failed_checks:
        out(f"  FAILED: {name}")

    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "verify.log").write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    sys.exit(1 if failed_checks else 0)


if __name__ == "__main__":
    main()
