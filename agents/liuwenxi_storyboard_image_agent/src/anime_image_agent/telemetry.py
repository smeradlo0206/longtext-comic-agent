from __future__ import annotations

import json
import signal
import time
from pathlib import Path
from typing import Any

from .io_utils import now


def gpu_sample(pynvml: Any, index: int) -> dict[str, Any]:
    handle = pynvml.nvmlDeviceGetHandleByIndex(index)
    memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
    utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
    return {
        "index": index,
        "memory_used_mib": round(memory.used / 1024**2, 3),
        "memory_total_mib": round(memory.total / 1024**2, 3),
        "gpu_utilization": utilization.gpu,
        "memory_utilization": utilization.memory,
        "power_watts": round(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000, 3),
        "temperature_c": pynvml.nvmlDeviceGetTemperature(
            handle, pynvml.NVML_TEMPERATURE_GPU
        ),
    }


def monitor(output: Path, stop_file: Path, interval: float = 1.0) -> None:
    import pynvml

    stopped = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    output.parent.mkdir(parents=True, exist_ok=True)
    pynvml.nvmlInit()
    try:
        count = pynvml.nvmlDeviceGetCount()
        if count != 8:
            raise RuntimeError(f"telemetry expected 8 GPUs, found {count}")
        with output.open("a", encoding="utf-8") as stream:
            while not stopped and not stop_file.exists():
                payload = {
                    "timestamp": now().isoformat(),
                    "monotonic_seconds": round(time.monotonic(), 3),
                    "gpus": [gpu_sample(pynvml, index) for index in range(count)],
                }
                stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                time.sleep(interval)
    finally:
        pynvml.nvmlShutdown()


def summarize(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"samples": 0, "duration_seconds": 0.0, "per_gpu": {}}
    peaks: dict[int, dict[str, float | int]] = {}
    samples = 0
    first_monotonic: float | None = None
    last_monotonic: float | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        samples += 1
        first_monotonic = first_monotonic or payload["monotonic_seconds"]
        last_monotonic = payload["monotonic_seconds"]
        for gpu in payload["gpus"]:
            peak = peaks.setdefault(
                gpu["index"],
                {
                    "peak_memory_mib": 0.0,
                    "peak_gpu_utilization": 0,
                    "peak_power_watts": 0.0,
                    "peak_temperature_c": 0,
                },
            )
            peak["peak_memory_mib"] = max(float(peak["peak_memory_mib"]), gpu["memory_used_mib"])
            peak["peak_gpu_utilization"] = max(int(peak["peak_gpu_utilization"]), gpu["gpu_utilization"])
            peak["peak_power_watts"] = max(float(peak["peak_power_watts"]), gpu["power_watts"])
            peak["peak_temperature_c"] = max(int(peak["peak_temperature_c"]), gpu["temperature_c"])
    duration = (last_monotonic or 0.0) - (first_monotonic or 0.0)
    return {
        "samples": samples,
        "duration_seconds": round(duration, 3),
        "per_gpu": {str(index): value for index, value in sorted(peaks.items())},
    }
