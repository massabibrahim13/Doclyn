"""Today's token spend. Reads the local ledger — makes no API call, costs nothing.

    python scripts\\check_budget.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, usage  # noqa: E402

rows = usage.today_entries()
spent = usage.today_total()
left = usage.remaining_today()
pct = (spent / config.DAILY_TOKEN_BUDGET * 100) if config.DAILY_TOKEN_BUDGET else 0

bar_width = 40
filled = min(bar_width, int(bar_width * pct / 100))

print(f"\nDoclyn budget — {usage._today()} (UTC)")
print("=" * 52)
print(f"  [{'#' * filled}{'.' * (bar_width - filled)}] {pct:.1f}%")
print(f"  spent today : {spent:,} tokens across {len(rows)} call(s)")
print(f"  remaining   : {left:,} of {config.DAILY_TOKEN_BUDGET:,}")

groq_left = usage.last_groq_remaining()
if groq_left is not None:
    print(f"  Groq said   : {groq_left:,} tokens left that minute (last call)")

if rows:
    print("\n  recent calls:")
    for row in rows[-5:]:
        total = row.get("input_tokens", 0) + row.get("output_tokens", 0)
        print(f"    {row['ts'][11:19]}  {row['endpoint']:<16} {total:>6,} tokens")

print()
