from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .playwright_observation import UploadedAsset


def append_checkpoint(path: Path, package_digest: str, phase: str,
                      uploads: tuple[UploadedAsset, ...], save_attempted: bool) -> None:
    record = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'package_digest': package_digest, 'phase': phase,
              'filenames': [item.filename for item in uploads],
              'save_attempted': save_attempted}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        _ = output.write(json.dumps(record, ensure_ascii=False) + '\n')
        output.flush()
        os.fsync(output.fileno())
