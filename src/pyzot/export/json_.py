"""JSON export — full-fidelity item dump."""

from __future__ import annotations

import json
from typing import IO

from pyzot.models import Item


def items_to_json(items: list[Item], fp: IO[str] | None = None) -> str:
    data = [item.model_dump(mode="json") for item in items]
    output = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    if fp is not None:
        fp.write(output)
    return output
