# Admissions Yield Planner

Standalone Track B classroom application using Python, Gurobi, and Streamlit.

## Start the app

On this computer, double-click `run_app.bat`, then open
http://127.0.0.1:8501. This uses the local `.venv` created during setup.

For a new computer, open a terminal in this folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Use Python 3.14 (tested locally) and your own working Gurobi license. No API
key or online data access is needed to run the app. Dependencies are pinned
direct versions, not a full transitive lockfile. The development environment
here reuses existing system packages; a completely clean installation on
another device has not yet been tested. Other operating systems use their
equivalent virtual-environment Python path.

## Data and the real versus assumed distinction

`data/tuition_sources.json` records the official source, verification date,
scope, and four published 2026–27 annual tuition-and-mandatory-fee amounts:

| Residency | Base rate | Business Tier 4 |
|---|---:|---:|
| In-state | $15,014 | $21,254 |
| Out-of-state | $46,058 | $50,166 |

Source: https://www.colorado.edu/bursar/costs/undergraduate
Accessed November 14, 2026. These are incoming full-time fall/spring rates.
Resident figures are the student share after COF. One-time new student
fees, housing, books, and aid are excluded. The objective is a proxy for
annual student tuition-and-fee receipts, not total institutional revenue,
net revenue, or profit; it excludes COF receipts and operating expenses.

Mapping GA to Base and DA to Business is an assumption, not a verified
CU admissions rule. The interface supports using Base for both tiers.
All applicant counts, yield rates, capacities, composition targets, and
the assumption that every enrollee needs a bed are hypothetical. This is
not an individual admissions system or a statement of university policy.

`data/applicant_pools.csv` stores each group's original `total_applicants`
once (four rows). `data/tier_inputs.csv` stores yields and tuition for the
eight group-tier combinations, without repeated applicant counts.
The older `data/admissions_inputs.csv` is retained as a legacy snapshot and
is no longer read by the app. Half-up rounding applies to each group's waitlist once; 10%
reserves 1,500 applicants. All rates and shares use fractions, not percentages.
This app's data folder contains the completed dataset used by the model.

## Model

Integer admits a[g,t] maximize sum(tuition[g,t] * yield[g,t] * a[g,t]).
All applicants initially enter one pool per group. Define a nonnegative
integer GA consideration count q[g] = total_applicants[g] - DA_offers[g].
Then GA_offers[g] + waitlisted[g] + denied[g] = q[g], with denied >= 0.
Consequently DA offers + GA offers + waitlisted + denied equals the original
pool. The GA consideration count is an output, not an independent input.
It includes everyone without a DA offer; GA offers, waitlist and denials
are the subsequent mutually exclusive outcomes. A DA offer that is declined
does not return to the GA pool in this single-round model.

The solver chooses both tiers jointly. This flow formulation does not add
a separate priority objective that maximizes DA offers first.
All individual male/female admit variables already have lower bound zero.
Named non-negativity constraints additionally make these restrictions
explicit for every group/tier and male/female expected-enrollment total.
Independent result checks verify that GA consideration, GA allocations,
denials and male/female enrollment cannot be negative.
Expected total enrollment cannot exceed beds. Expected DA enrollment cannot
exceed program seats. Enforce in-state minimum and female lower/upper shares
on expected enrollment within each tier. Denied equals the remaining pool.
All rates are static. Actual enrollment may exceed capacity despite these
expected-value constraints. Scholarships, retention, and waitlist offers in
a second round are outside the model.

Zero enrollment satisfies share constraints. The optional minimum expected
enrollment setting permits meaningful infeasibility demonstrations and is
off by default. For an empty tier, shares are undefined and displayed blank.
IIS reports one conflicting subset, not necessarily a unique explanation.

LP capacity duals are continuous-model local sensitivities, not integer
shadow prices. The app compares them with actual one-bed/one-seat integer
re-solves and an in-state-target increase of one percentage point. A small
LP objective gap does not prove integer marginal-value accuracy.

The proportional benchmark uses common admission fractions across groups
within each tier, permits ±1 applicant rounding, and optimizes the DA/GA mix
subject to the same policies. This is a constrained reference policy, not
an empirical claim about current university practice. All reference results
come from live solves.

## Files and checks

- `admissions_model.py`: validation, integer optimization, independent
  feasibility checks, LP relaxation, marginal re-solves, and benchmark.
- `app.py`: editable inputs, plan and exports, limits, saved scenario
  comparisons, capacity sweep, and model explanations.
- `test_model.py`: independent enumeration, accounting, status, validation,
  monotonicity, and Streamlit interaction tests.

```powershell
.\.venv\Scripts\python.exe admissions_model.py
.\.venv\Scripts\python.exe -m unittest test_model -v
```

No admission plan is displayed when no feasible solution is available or
independent checks fail. Feasible time-limited results are labeled as
incumbents, not certified optima. Solves have a 20-second limit and request
0.01% relative MIP gap and use two threads. Comparisons of nonoptimal incumbents are not certified policy
effects; check the displayed statuses.

For the recorded demo, solve the default, reduce beds from 1,000 to 800,
raise the in-state minimum, and compare saved scenarios. Demonstrate a
minimum enrollment above bed capacity to show infeasibility handling.
Finalize the 3–5-page memo, 10–15-minute recording, and factual AI-use
statement separately before the Track B submission.

## Synthetic admissions dataset

[`data/synthetic_admissions_dataset_v2/`](data/synthetic_admissions_dataset_v2/README.md)
contains 75,000 explicitly synthetic applicants across five simulated cycles,
20 applicant-flow summaries, and yields for all eight group/tier combinations.
The original pool appears once per group; GA consideration is the remainder
after DA offers. The package includes assumptions and a seeded generator.
These are not historical CU admissions records or evidence of yield accuracy.

The app continues to use its baseline inputs by default. To solve a separate
synthetic scenario through the backend:

```python
import json
from pathlib import Path
import pandas as pd
from admissions_model import solve

folder = Path(__file__).resolve().parent / "data/synthetic_admissions_dataset_v2"
frame = pd.read_csv(folder / "synthetic_model_inputs.csv")
settings = json.loads((folder / "synthetic_scenario_settings.json").read_text())
result = solve(frame, settings)
```

Save this snippet as a Python file in the app folder. The four original
applicant pools are supplied through settings, not repeated on tier rows.
