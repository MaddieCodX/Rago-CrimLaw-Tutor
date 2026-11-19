"""
audit.py -- a tamper-evident activity log for the Crim Pro tutor.

WHAT IT RECORDS
  Every meaningful step of a session: which slide deck and which version of the code
  were in use, each office-hours question and answer, each hypo and its hidden answer
  key, the student's timed answer and how long it took, every grade, every follow-up
  question and reply, and the final score.

WHY IT CAN'T BE QUIETLY EDITED
  Each entry is fingerprinted with SHA-256 -- the same function Code Colloquy uses on
  your transcripts (Class 2). And each entry's fingerprint covers the PREVIOUS entry's
  fingerprint too, so the entries form a chain:

      entry 1  ->  hash A
      entry 2  (includes A)  ->  hash B
      entry 3  (includes B)  ->  hash C

  Change one character of entry 2 and its hash no longer matches; delete entry 2 and
  entry 3 points to a hash that isn't there. verify_log() walks the chain and reports
  the first break. Nothing is secret -- integrity comes from comparison, not hiding.

  What a chain cannot stop is someone deleting the whole file, or rewriting it from
  scratch and recomputing every hash. Saving the last hash somewhere else (an email
  to yourself, a printed report) closes that gap: a rewritten log won't end in it.

FORMAT
  One JSON object per line ("JSON Lines"), so the file can be appended to without
  rewriting it and read by pandas with pd.read_json(path, lines=True).
"""

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64        # the "previous hash" for the very first entry


def sha256_text(text):
    """The full SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(text):
    """A short fingerprint: the first 12 characters of the SHA-256 digest,
    the same convention Code Colloquy uses."""
    return sha256_text(text)[:12]


def _entry_hash(entry):
    """Hash every field of the entry except "hash" itself. sort_keys=True makes the
    JSON identical every time, so the same entry always produces the same hash."""
    body = {key: value for key, value in entry.items() if key != "hash"}
    return sha256_text(json.dumps(body, sort_keys=True, ensure_ascii=False))


class AuditLog:
    """An append-only, hash-chained log file."""

    def __init__(self, path="audit_log.jsonl"):
        self.path = path
        self._lock = threading.Lock()      # in the web app, several students may write at once
        self._seq, self._last_hash = self._read_tail()

    def _read_tail(self):
        """Pick up where an existing log left off, so the chain continues across runs."""
        seq, last = 0, GENESIS_HASH
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        seq, last = entry["seq"], entry["hash"]
        except FileNotFoundError:
            pass
        return seq, last

    def record(self, session_id, event, details):
        """Add one entry to the end of the chain and return it."""
        with self._lock:
            entry = {
                "seq": self._seq + 1,
                "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "session": session_id,
                "event": event,
                "details": details,
                "prev_hash": self._last_hash,
            }
            entry["hash"] = _entry_hash(entry)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._seq, self._last_hash = entry["seq"], entry["hash"]
            return entry

    def last_hash(self):
        return self._last_hash


def new_session_id():
    """A random, anonymous id for one student's visit. No names or emails are logged."""
    return uuid.uuid4().hex[:8]


def verify_log(path):
    """Walk the chain. Returns (True, summary) if every link holds, or (False, the
    first problem found) if anything was edited, deleted, inserted, or reordered."""
    previous = GENESIS_HASH
    expected_seq = 1
    count = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return False, f"Line {line_number} is not valid JSON -- the file was damaged."
                if entry.get("seq") != expected_seq:
                    return False, (f"Line {line_number}: expected entry #{expected_seq} but found "
                                   f"#{entry.get('seq')} -- an entry was removed or reordered.")
                if entry.get("prev_hash") != previous:
                    return False, (f"Entry #{expected_seq} does not link to the entry before it "
                                   "-- something before it was changed or removed.")
                if _entry_hash(entry) != entry.get("hash"):
                    return False, f"Entry #{expected_seq} was altered after it was written."
                previous = entry["hash"]
                expected_seq += 1
                count += 1
    except FileNotFoundError:
        return False, f"No log file at {path}."
    if count == 0:
        return True, "The log is empty."
    return True, f"All {count} entries verified. Final hash: {previous[:12]}"


if __name__ == "__main__":
    # From a terminal or Colab:  !python audit.py audit_log.jsonl
    import sys
    log_path = sys.argv[1] if len(sys.argv) > 1 else "audit_log.jsonl"
    ok, message = verify_log(log_path)
    print(("VERIFIED: " if ok else "PROBLEM: ") + message)
