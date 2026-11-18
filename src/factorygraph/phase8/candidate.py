"""One bounded candidate: immutable startup metadata indexes, no report cache."""

import time

import psutil

from factorygraph.phase6.common import digest, iso
from factorygraph.phase7.runtime import Runtime
from factorygraph.phase8.common import budget


class CandidateRuntime(Runtime):
    def __init__(self, settings):
        started = time.perf_counter()
        super().__init__(settings)
        if settings.mode == "gallery":
            return
        try:
            budget(psutil.Process())
            self.metadata_identity = digest(
                {
                    "mode": settings.mode,
                    "config": self.builder.config.digest(),
                    "inputs": self.builder.registry.hashes,
                }
            )
            self._machine_descriptors = tuple(
                (r["machine_id"], r["model"]) for r in super().machines()
            )
            grouped = {}
            primary = self.builder.predictions.index.index
            for machine, timestamp in self.builder.temporal.context.index:
                grouped.setdefault(int(machine), []).append(
                    (
                        iso(timestamp),
                        "primary" if (machine, timestamp) in primary else "evidence_only",
                    )
                )
            self._snapshot_descriptors = {m: tuple(rows) for m, rows in grouped.items()}
            self.metadata_index_build_seconds = time.perf_counter() - started - self.startup_seconds
            self.startup_seconds = time.perf_counter() - started
            budget(psutil.Process())
        except Exception:
            self.close()
            raise

    def machines(self):
        if self.settings.mode == "gallery":
            return super().machines()
        return [{"machine_id": m, "model": model} for m, model in self._machine_descriptors]

    def snapshots(self, machine):
        if self.settings.mode == "gallery":
            return super().snapshots(machine)
        return [
            {"snapshot": timestamp, "eligibility": eligibility}
            for timestamp, eligibility in self._snapshot_descriptors.get(machine, ())
        ]
