from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PreparationRun:
    root: Path
    directory: Path
    run_id: str
    clock: Callable[[], datetime]
