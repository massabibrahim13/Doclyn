"""Stage 0 verification (§10.0).

Run from the project root, with the venv active:

    python scripts/check_env.py

Checks the four things that silently break Stage 1 if they're wrong, and prints
NO secrets — only whether a key was found and its last 4 characters.
"""

import sys
from pathlib import Path

# When you run `python scripts/check_env.py`, Python puts scripts/ on sys.path —
# not the project root. So `import backend.config` would fail with
# ModuleNotFoundError. This line puts the project root on the path first.
# (A package installed with `pip install -e .` wouldn't need this; we're not
# doing that in v1.)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402  (import must follow the sys.path fix)

OK, BAD = "[ OK ]", "[FAIL]"
problems = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global problems
    if not condition:
        problems += 1
    print(f"{OK if condition else BAD} {label}" + (f"  — {detail}" if detail else ""))


print("\nDoclyn — Stage 0 environment check")
print("=" * 58)

# 1. Which interpreter is actually running? This is the Anaconda trap (§10.0):
#    if this path is not inside your project's .venv, your `pip install` landed
#    somewhere else and Stage 1 will fail on imports you thought you installed.
print(f"\nInterpreter : {sys.executable}")
print(f"Version     : {sys.version.split()[0]}")
in_venv = sys.prefix != sys.base_prefix
check(in_venv, "Running inside a virtual environment",
      "" if in_venv else "activate .venv first — see Stage 0")
check(sys.version_info >= (3, 11), "Python 3.11+")

# 2. Dependencies importable. Import name != package name for several of these,
#    which is why this list exists rather than parsing requirements.txt.
print()
for module, package in [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("pydantic", "pydantic"),
    ("dotenv", "python-dotenv"),
    ("openai", "openai"),
    ("chromadb", "chromadb"),
    ("sentence_transformers", "sentence-transformers"),
    ("pypdf", "pypdf"),
    ("streamlit", "streamlit"),
    ("httpx", "httpx"),
]:
    try:
        __import__(module)
        check(True, f"import {module}")
    except ImportError:
        check(False, f"import {module}", f"pip install {package}")

# 3. Config + secret loading. The key is never printed in full.
print()
key = config.LLM_API_KEY
check(bool(key), "GROQ_API_KEY loaded from .env",
      f"...{key[-4:]}" if key else "create .env from .env.example")
check((config.PROJECT_ROOT / ".env").exists(), ".env exists at project root")
check((config.PROJECT_ROOT / ".env.example").exists(), ".env.example committed")

# 4. Stub mode — printed loudly because it decides whether tokens get spent.
print()
print(f"       STUB_MODE = {config.STUB_MODE}"
      f"   ({'canned answers, zero quota' if config.STUB_MODE else 'REAL Groq calls'})")
print(f"       Daily budget = {config.DAILY_TOKEN_BUDGET:,} tokens")
print(f"       Model = {config.LLM_MODEL} via {config.PROVIDER_NAME}")

print("\n" + "=" * 58)
print("Stage 0 complete." if problems == 0 else f"{problems} problem(s) above.")
sys.exit(1 if problems else 0)
