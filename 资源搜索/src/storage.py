import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "data"


class JsonlWriter:
    """Append-only JSONL writer with size tracking and dedup."""

    def __init__(self, source: str, max_bytes: int = 1 * 1024 * 1024 * 1024):
        self.source = source
        self.max_bytes = max_bytes
        self._path = DATA_DIR / f"{source}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._written_ids: set[str] = set()
        self._total_bytes = 0
        self._load_existing()

    def _load_existing(self):
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    self._written_ids.add(record.get("id", ""))
                except json.JSONDecodeError:
                    continue
        self._total_bytes = self._path.stat().st_size

    def write(self, record: dict) -> bool:
        """Write a record if not duplicate and within size limit. Returns True if written."""
        rid = record.get("id", hashlib.md5(f"{self.source}:{record.get('url','')}".encode()).hexdigest())
        if rid in self._written_ids:
            return False
        record["id"] = rid
        record.setdefault("crawled_at", datetime.now(timezone.utc).isoformat())
        record.setdefault("source", self.source)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        line_bytes = len(line.encode("utf-8"))
        if self._total_bytes + line_bytes > self.max_bytes:
            return False
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)
        self._written_ids.add(rid)
        self._total_bytes += line_bytes
        return True

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def count(self) -> int:
        return len(self._written_ids)

    def size_exceeded(self) -> bool:
        return self._total_bytes >= self.max_bytes


def merge_all(output_path: str | None = None):
    """Merge all per-source JSONL files into one, deduplicating by id."""
    output_path = Path(output_path or DATA_DIR / "all.jsonl")
    seen = set()
    count = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for jsonl_file in sorted(DATA_DIR.glob("*.jsonl")):
            if jsonl_file.name == "all.jsonl":
                continue
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rid = record.get("id", "")
                    if rid in seen:
                        continue
                    seen.add(rid)
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
    print(f"Merged {count} records -> {output_path}")
