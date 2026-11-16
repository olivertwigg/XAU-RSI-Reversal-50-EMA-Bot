"""
Plot Monte Carlo equity paths saved by `backtest.py --mc`.

Usage:
  python3 plot_mc.py              # draws 100 sample paths
  python3 plot_mc.py --paths 500
Saves mc_paths.png and opens the chart.
"""

import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from backtest import CAPITAL

ap = argparse.ArgumentParser()
ap.add_argument("--paths", type=int, default=100,
                help="how many random paths to draw (all are used for percentiles)")
args = ap.parse_args()

paths = np.load("mc_paths.npy")
trials, n = paths.shape
x = np.arange(1, n + 1)

fig, ax = plt.subplots(figsize=(12, 6))

# faint sample of individual paths
idx = np.random.default_rng().choice(trials, min(args.paths, trials), replace=False)
ax.plot(x, paths[idx].T, alpha=0.4, linewidth=0.8)

# percentile bands across all trials
p5, p50, p95 = np.percentile(paths, [5, 50, 95], axis=0)
ax.plot(x, p5, color="black", linewidth=1.5, linestyle=":", label="5th / 95th pct")
ax.plot(x, p95, color="black", linewidth=1.5, linestyle=":")
ax.plot(x, p50, color="black", linewidth=2.5, label="median")

# the real backtest path, if it matches this run
try:
    actual = CAPITAL + pd.read_csv("equity_curve.csv")["equity_usd_per_oz"].to_numpy()
    if len(actual) == n:
        ax.plot(x, actual, color="tab:orange", linewidth=2, label="actual backtest")
except FileNotFoundError:
    pass

ax.axhline(CAPITAL, color="black", linewidth=1, linestyle="--", label=f"${CAPITAL:.0f} start")
ax.set_title(f"Monte Carlo equity paths — {trials:,} trials x {n} trades")
ax.set_xlabel("Trade number")
ax.set_ylabel("Balance ($)")
ax.legend(loc="upper left")
ax.grid(alpha=0.3)

fig.tight_layout()
fig.savefig("mc_paths.png", dpi=150)
print("Saved: mc_paths.png")
plt.show()
