"""Matched real HTTP requests, graceful owned lifecycle and raw auditable records."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new
from factorygraph.phase7.runtime import project
from factorygraph.phase8.common import ROOT, budget, config


class Service:
    def __init__(self, variant, directory):
        self.variant, self.directory = variant, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.process = self.worker = None
        self.samples = []
        self.finished = threading.Event()
        self.violation = None
        self.token = Path("artifacts/phase7/secrets/operator.token").read_text()
        self.viewer = Path("artifacts/phase7/secrets/viewer.token").read_text()

    def __enter__(self):
        env = os.environ.copy()
        env.update(
            {
                "FG8_VARIANT": self.variant,
                "FG8_OUTPUT": str(self.directory.resolve()),
                "FG7_MODE": "full",
                "FG7_OPERATOR_TOKEN_FILE": str(
                    Path("artifacts/phase7/secrets/operator.token").resolve()
                ),
                "FG7_VIEWER_TOKEN_FILE": str(
                    Path("artifacts/phase7/secrets/viewer.token").resolve()
                ),
            }
        )
        self.started = time.perf_counter()
        with (self.directory / "server.log").open("w", encoding="utf-8") as stream:
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            self.process = subprocess.Popen(
                [sys.executable, "-m", "factorygraph.phase8.server"],
                env=env,
                stdout=stream,
                stderr=stream,
                **kwargs,
            )
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{config()['port']}",
            timeout=120,
            headers={"Authorization": "Bearer " + self.token},
            trust_env=False,
        )
        try:
            while time.perf_counter() - self.started < 60:
                if self.process.poll() is not None:
                    raise RuntimeError("Study service startup failed; retain logs")
                try:
                    r = self.client.get("/api/v1/health/ready", timeout=2)
                    if r.status_code == 200 and (self.directory / "engine.json").exists():
                        self.worker = psutil.Process(
                            read_json(self.directory / "engine.json")["pid"]
                        )
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            if self.worker is None:
                raise TimeoutError("Registered startup deadline")
            self.startup_seconds = time.perf_counter() - self.started
            self.monitor = threading.Thread(target=self.sample, daemon=True)
            self.monitor.start()
            return self
        except Exception:
            self.__exit__(*sys.exc_info())
            raise

    def sample(self):
        while not self.finished.wait(0.1):
            try:
                self.samples.append(
                    {
                        "elapsed": time.perf_counter() - self.started,
                        "rss_bytes": self.worker.memory_info().rss,
                        "available_ram_bytes": psutil.virtual_memory().available,
                    }
                )
                c = config()
                if self.samples[-1]["rss_bytes"] > c["maximum_service_rss_bytes"]:
                    self.violation = "service_rss_cap"
                if self.samples[-1]["available_ram_bytes"] < c["minimum_available_ram_bytes"]:
                    self.violation = "available_ram_floor"
            except psutil.Error:
                return

    def request(self, name, method, path, expected=200, **kwargs):
        if self.violation:
            raise MemoryError(self.violation)
        budget(self.worker)
        started = time.perf_counter()
        cpu = sum(self.worker.cpu_times()[:2])
        record = {"scenario": name, "method": method, "path": path}
        try:
            with self.client.stream(method, path, **kwargs) as response:
                record["headers_seconds"] = time.perf_counter() - started
                body = response.read()
                record["body_complete_seconds"] = time.perf_counter() - started
                record["status"] = response.status_code
            decode = time.perf_counter()
            value = json.loads(body)
            record["decode_seconds"] = time.perf_counter() - decode
            record["http_seconds"] = time.perf_counter() - started
            record["worker_cpu_seconds_delta"] = sum(self.worker.cpu_times()[:2]) - cpu
            record["response_bytes"] = len(body)
            record["body_sha256"] = hashlib.sha256(body).hexdigest()
            with self.lock:
                number = len(self.records)
                record["response_file"] = f"response-{number:03d}.json"
                (self.directory / record["response_file"]).write_bytes(body)
                self.records.append(record)
            if record["status"] != expected:
                raise AssertionError(f"Unexpected {name} HTTP status {record['status']}")
            if self.violation:
                raise MemoryError(self.violation)
            return value
        except Exception as error:
            if "status" not in record:
                record["failure"] = type(error).__name__
                record["http_seconds"] = time.perf_counter() - started
                with self.lock:
                    self.records.append(record)
            raise

    def initialize_records(self):
        self.records, self.lock = [], threading.Lock()

    def __exit__(self, *_args):
        start = time.perf_counter()
        if self.process is not None:
            (self.directory / "stop").touch()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                root = psutil.Process(self.process.pid)
                for p in reversed([root, *root.children(recursive=True)]):
                    try:
                        p.terminate()
                    except psutil.NoSuchProcess:
                        pass
                save_new(
                    self.directory / "forced_stop.json", {"failure": "graceful_close_deadline"}
                )
        self.finished.set()
        if hasattr(self, "monitor"):
            self.monitor.join(timeout=2)
        if hasattr(self, "client"):
            self.client.close()
        if hasattr(self, "records"):
            save_new(self.directory / "requests.json", self.records)
            save_new(
                self.directory / "resources.json",
                {
                    "startup_to_ready_seconds": getattr(self, "startup_seconds", None),
                    "shutdown_seconds": time.perf_counter() - start,
                    "graceful_closed": (self.directory / "closed.json").exists(),
                    "rss_samples": self.samples,
                    "budget_violation": self.violation,
                },
            )


def references(service, repeats):
    refs = read_json(ROOT / "registration.json")["references"]
    for _ in range(repeats):
        for r in refs:
            body = service.request(
                r["name"],
                "GET",
                f"/api/v1/cases/{r['machine_id']}",
                params={"snapshot_time": r["snapshot"]},
            )
            expected = project(read_json(f"docs/examples/phase6/{r['name']}.json"))
            assert body["report"] == expected


def controls(service):
    r = read_json(ROOT / "registration.json")["boundary"]
    service.request(
        "boundary_unsupported",
        "GET",
        f"/api/v1/cases/{r['machine_id']}",
        expected=404,
        params={"snapshot_time": r["snapshot"]},
    )
    amendment = read_json(ROOT / "harness_amendment.json")
    r = amendment["supported_evidence_only"]
    result = service.request(
        "evidence_only",
        "GET",
        f"/api/v1/cases/{r['machine_id']}",
        params={"snapshot_time": r["snapshot"]},
    )
    assert result["report"] == project(read_json(amendment["accepted_report_path"]))
    for name, machine, snapshot, status, headers in [
        ("unknown_machine", 10001, "2015-10-15T00:00Z", 404, None),
        ("unsupported_time", 17, "2015-10-15T00:01Z", 404, None),
        (
            "invalid_credential",
            17,
            "2015-10-15T00:00Z",
            401,
            {"Authorization": "Bearer invalid-study-control"},
        ),
        (
            "viewer_denied",
            1,
            "2015-10-15T00:00Z",
            403,
            {"Authorization": "Bearer " + service.viewer},
        ),
        (
            "viewer_allowed",
            17,
            "2015-10-15T00:00Z",
            200,
            {"Authorization": "Bearer " + service.viewer},
        ),
    ]:
        kwargs = {"headers": headers} if headers else {}
        service.request(
            name,
            "GET",
            f"/api/v1/cases/{machine}",
            expected=status,
            params={"snapshot_time": snapshot},
            **kwargs,
        )


def fleet(service, size, repeats):
    c = config()
    for _ in range(repeats):
        body = service.request(
            f"fleet_{size}",
            "POST",
            "/api/v1/fleet/replay",
            json={
                "snapshot": c["fleet_snapshot"],
                "machines": c["small_fleet"] if size == 3 else list(range(1, 101)),
            },
        )
        assert len(body["reports"]) == size
        assert [r["request"]["machine_id"] for r in body["reports"]] == (
            c["small_fleet"] if size == 3 else list(range(1, 101))
        )


def concurrent(service):
    barrier = threading.Barrier(3)

    def work(i):
        barrier.wait()
        # This cohort preserves both accepted 200 and expected bounded busy 503.
        with httpx.Client(
            base_url=service.client.base_url,
            timeout=120,
            trust_env=False,
            headers={"Authorization": "Bearer " + service.token},
        ) as client:
            start = time.perf_counter()
            response = client.get("/api/v1/cases/17", params={"snapshot_time": "2015-10-15T00:00Z"})
            return {
                "scenario": "concurrent",
                "member": i,
                "status": response.status_code,
                "http_seconds": time.perf_counter() - start,
                "body_sha256": hashlib.sha256(response.content).hexdigest(),
            }

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        result = list(pool.map(work, range(3)))
    assert sorted(r["status"] for r in result) == [200, 503, 503]
    save_new(
        service.directory / "concurrency.json",
        {"wall_seconds": time.perf_counter() - start, "requests": result},
    )


def profile(attempt="baseline_profile"):
    freeze = {p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase8").glob("*.py")}
    save_new(ROOT / f"{attempt}_implementation.json", freeze)
    started = time.perf_counter()
    with Service("profile", ROOT / attempt) as service:
        service.initialize_records()
        references(service, 1)
        controls(service)
        fleet(service, 3, 1)
        fleet(service, 100, 1)
        service.request("metrics", "GET", "/api/v1/metrics")
    assert time.perf_counter() - started < config()["max_benchmark_seconds"]
    return {"status": "baseline_profile_saved", "seconds": time.perf_counter() - started}


def compare():
    candidate = read_json(ROOT / "candidate_registration.json")
    for p, h in candidate["implementation_sha256"].items():
        if sha256(Path(p)) != h:
            raise ValueError("Registered candidate changed")
    started = time.perf_counter()
    for number, variant in enumerate(config()["block_order"]):
        if time.perf_counter() - started > config()["max_benchmark_seconds"]:
            raise TimeoutError("Registered study budget")
        budget()
        with Service(variant, ROOT / f"block-{number}-{variant}") as service:
            service.initialize_records()
            for _ in range(config()["warmups_per_block"]):
                service.request(
                    "warmup",
                    "GET",
                    "/api/v1/cases/17",
                    params={"snapshot_time": "2015-10-15T00:00Z"},
                )
            tick = time.perf_counter()
            cpu = sum(service.worker.cpu_times()[:2])
            references(service, config()["reference_repeats_per_block"])
            controls(service)
            fleet(service, 3, config()["small_fleet_repeats_per_block"])
            fleet(service, 100, config()["full_fleet_repeats_per_block"])
            save_new(
                service.directory / "serial_window.json",
                {
                    "wall_seconds": time.perf_counter() - tick,
                    "worker_cpu_seconds_delta": sum(service.worker.cpu_times()[:2]) - cpu,
                    "measured_requests": len(service.records) - config()["warmups_per_block"],
                    "competing_load": budget(service.worker),
                },
            )
            concurrent(service)
            service.request("metrics", "GET", "/api/v1/metrics")
        if not read_json(service.directory / "resources.json")["graceful_closed"]:
            raise ValueError("Application lifespan did not close")
        print({"block": number, "variant": variant, "completed": True}, flush=True)
    save_new(
        ROOT / "comparison_complete.json",
        {"seconds": time.perf_counter() - started, "blocks": len(config()["block_order"])},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["profile", "compare"])
    parser.add_argument(
        "--attempt",
        choices=["baseline_profile", "baseline_profile_corrected"],
        default="baseline_profile",
    )
    args = parser.parse_args()
    print(profile(args.attempt) if args.stage == "profile" else compare())
