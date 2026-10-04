"""Worker entry point. Run with: python -m services.workers.app.main"""


from arq import run_worker
from services.workers.app.worker import WorkerSettings


def main() -> None:
    """Start the Arq worker process."""
    run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
