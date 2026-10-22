"""Create a local operator key without printing it or overwriting existing access."""
import hashlib
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = root / ".env"
content = env.read_text() if env.exists() else (root / ".env.example").read_text()
existing = [line for line in content.splitlines() if line.startswith("WEB_PASSWORD_SHA256=") and len(line.split("=", 1)[1]) == 64]
if existing:
    raise SystemExit("Access already configured; existing key preserved.")
key = secrets.token_urlsafe(24)
lines = [line for line in content.splitlines() if not line.startswith("WEB_PASSWORD_SHA256=")]
lines.append("WEB_PASSWORD_SHA256=" + hashlib.sha256(key.encode()).hexdigest())
env.write_text("\n".join(lines) + "\n")
os.chmod(env, 0o600)
folder = root / "runs"
folder.mkdir(exist_ok=True)
access = folder / "control-room-access.txt"
access.write_text("Don’t Die control room\nAccess key: " + key + "\nKeep private: this grants operator control.\n")
os.chmod(access, 0o600)
print("Private access instructions saved in runs/control-room-access.txt; key not printed.")
