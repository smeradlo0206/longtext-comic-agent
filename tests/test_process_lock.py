import multiprocessing
from pathlib import Path

from flux2_agent.locking import exclusive_lock


def _increment(path, result):
    for _ in range(10):
        with exclusive_lock(Path(path)):
            value = int(Path(result).read_text())
            Path(result).write_text(str(value + 1))


def test_lock_serializes_processes(tmp_path):
    result = tmp_path / "counter.txt"
    result.write_text("0")
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_increment, args=(str(tmp_path / "lock"), str(result)))
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert result.read_text() == "30"
