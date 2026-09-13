"""Render docs/demo.svg from a real run of demo.py (scripted fake LLM, no keys).

    python scripts/make_readme_capture.py

The full output is ~110 lines, so the capture keeps steps 1-3 and the final
query result and marks the omitted middle explicitly.
"""
import io
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
lines = subprocess.run([sys.executable, "demo.py"], cwd=ROOT, env=env, capture_output=True,
                       text=True, encoding="utf-8", check=True).stdout.rstrip().splitlines()

head_end = next(i for i, s in enumerate(lines) if s.startswith("Assertion passed")) + 1
step5 = next(i for i, s in enumerate(lines) if s.startswith("STEP 5/5")) - 1
kept = lines[:head_end] + [f"[... {step5 - head_end} lines omitted: per-lead timelines, dashboard, matching rows ...]"]
kept += lines[step5:step5 + 3] + lines[-1:]

console = Console(record=True, width=100, file=io.StringIO())
console.print(Text("$ python demo.py", style="bold green"))
for s in kept:
    console.print(Text(s, style="dim italic" if s.startswith("[...") else ""))
console.save_svg(str(ROOT / "docs" / "demo.svg"), title="recruit-voice-agent demo.py")
print("wrote docs/demo.svg")
