# Synthetic admissions dataset version 2

All admissions records are SYNTHETIC. They are not actual CU applicants or
historical university outcomes. This version corrects the applicant-pool
layout to match the updated admissions program. Version 1 is retained in a
separate folder for reference.

## Applicant flow

Everyone initially applies to DA. For each group and cycle:

    ga_consideration_pool = total_applicants - da_offers
    ga_offers + waitlisted + denied = ga_consideration_pool
    da_offers + ga_offers + waitlisted + denied = total_applicants

The GA consideration pool overlaps the original pool; never add it to the
original applicant count. It is not a separate group of new GA applicants.
Applicants with DA offers who decline are not subsequently reassigned to GA.
Every count is nonnegative. Zero is allowed; nonnegative does not mean
strictly positive.

## Files

- synthetic_applicants.csv: 75,000 unique simulated records, five cycles of
  15,000 each. The new flags applied_to_DA, da_offered, ga_considered, and
  ga_offered make each person's path explicit.
- synthetic_applicant_flow_by_cycle.csv: 20 rows, one per group and cycle.
  Contains total_applicants, da_offers, ga_consideration_pool, ga_offers,
  waitlisted, and denied. This is where original and remaining counts belong.
- synthetic_yields_by_cycle.csv: 40 rows for cycle/group/tier admitted,
  enrolled, and simulated yield. No repeated applicant pool column.
- synthetic_yields_pooled.csv: eight pooled group/tier yield summaries.
- synthetic_applicant_pools.csv: four original applicant counts for one
  planning scenario. Compatible with the updated app's applicant_pools.csv.
- synthetic_model_inputs.csv: eight tier rows with yields and tuition;
  no applicant count column. Compatible with the updated tier_inputs.csv.
- synthetic_scenario_settings.json: proposed scenario settings, including
  the original pools once, for the solve(frame, settings) backend API.
- generation_assumptions.json: random seed, assumptions and tuition provenance.
- generate_dataset.py: reproducible generator with accounting checks.

IM = in-state male, IF = in-state female, OM = out-of-state male,
OF = out-of-state female. DA = Direct Admit, GA = General Admit.
Original counts per cycle are 3,000, 3,750, 3,750 and 4,500 respectively.
The four-row model pool file totals 15,000, not 75,000. Cycles SIM_01 to
SIM_05 are simulation labels, not historical academic years.

## Record and summary definitions

Flags are 0 or 1. applied_to_DA is always 1; da_offered + ga_considered = 1;
ga_offered can be 1 only when ga_considered = 1. admission_decision records
the final DA, GA, WAITLIST or DENIED outcome. admission_tier is blank for
waitlist/denial, not a separate GA application. enrolled is a binary simulated
outcome and is zero for anyone without an offer.

Yields are fractions: enrolled / admitted. Enrollment_probability is the
assumed generating probability, not an empirically verified prediction.
Pooled yields are the ratio of pooled counts, not averaged cycle percentages.
annual_tuition_and_fees is the applicable reference charge for an admitted
applicant; it is blank for waitlist/denial. simulated_annual_receipts is
reference charge times enrolled, and is zero for non-enrollees. These are
simulated receipts, not actual payments or institutional net revenue.

## Generation assumptions

Seed 20261117. Each group's assumed outcome shares are 25% DA offers,
45% GA offers, 10% waitlist, and the remainder denied, using half-up rounding.
DA outcomes identify the applicants removed from further GA consideration;
the remaining outcomes partition the GA consideration pool. Random selection
does not imply merit ranking or an optimized DA-first priority policy.

GA baseline yields are IM .35, IF .26, OM .08, OF .06. DA is 1.5 times GA.
Cycle multipliers are .90, 1.05, .95, 1.10, 1.00, with an additional
Uniform(.95, 1.05) group/cycle factor shared by both tiers. Probabilities
are clipped to [.01, .99], and conditional Bernoulli draws determine
simulated enrollment. Assumed shared factors create some common variation;
remaining applicant outcomes are conditionally independent.

Every cycle uses the same published 2026-27 tuition-and-fee reference:
resident GA $15,014 / DA $21,254; nonresident GA $46,058 / DA $50,166.
Reference source verified November 14, 2026:
https://www.colorado.edu/bursar/costs/undergraduate
GA=Base and DA=Business is an assumed mapping. Resident charges are after
COF; COF funding, aid, housing, books, one-time fees, and costs are excluded.
No earlier-year prices or actual historical admissions are represented.

## Use and limitations

This dataset describes simulated applicant flows; its offer counts are not
optimized and are not forced to fit 1,000 beds or 700 DA program seats.
The planning model must choose its own offers using the synthetic yields.
It calculates new GA consideration pools from its chosen DA offers, rather
than treating the simulated GA pool as a fixed input for a future scenario.

The current app still loads its baseline data by default. This dataset does
not switch the app to synthetic yields or impose a DA-first priority
objective. For backend use:

    frame = pandas.read_csv('synthetic_model_inputs.csv')
    settings = json.load(open('synthetic_scenario_settings.json'))
    result = admissions_model.solve(frame, settings)

For sensitivity analysis, compare simulated cycles. For simulation-only
holdout checks, reserve the last cycle and estimate inputs from earlier
cycles; do not use all-cycle pooled yields for a claimed holdout exercise.
Additional synthetic rows do not establish real-world accuracy.

## Reproduce

Run python generate_dataset.py from this folder. It regenerates six CSVs,
two JSON files, and the ZIP in the parent directory. Checks verify IDs,
nonnegative counts, DA-to-GA flow, enrollment and receipts consistency,
and summary reconciliation. The same seed and Python version reproduce
the same outcomes.
