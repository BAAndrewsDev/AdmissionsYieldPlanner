"""Educational admissions allocation model; no individual admissions decisions."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json
import math

import gurobipy as gp
from gurobipy import GRB
import pandas as pd

ROOT = Path(__file__).resolve().parent
GROUPS = ("IM", "IF", "OM", "OF")
TIERS = ("GA", "DA")


def defaults():
    settings = json.loads((ROOT / "data/scenario_settings.json").read_text())
    pools = pd.read_csv(ROOT / "data/applicant_pools.csv")
    if len(pools) != 4 or set(pools.group) != set(GROUPS):
        raise ValueError("Applicant pools must contain each group exactly once.")
    settings["applicant_pools"] = dict(zip(pools.group, pools.total_applicants))
    return pd.read_csv(ROOT / "data/tier_inputs.csv"), settings


def validate(frame, settings):
    """Validate tier inputs and one original applicant pool per group."""
    data = frame.copy()
    needed = {"group", "tier", "yield_rate", "annual_tuition"}
    if not needed.issubset(data.columns):
        raise ValueError("Input table must contain " + ", ".join(sorted(needed)))
    if len(data) != 8 or set(zip(data.group, data.tier)) != {
            (g, t) for g in GROUPS for t in TIERS}:
        raise ValueError("Provide each of the four groups in both GA and DA exactly once.")
    if "applicants" in data.columns:
        raise ValueError("Use applicant_pools for original counts; tier rows must not repeat applicants.")
    for column in ("yield_rate", "annual_tuition"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
        if not all(math.isfinite(float(v)) for v in data[column]):
            raise ValueError(f"{column} contains a missing or nonnumeric value.")
    if any((data.yield_rate < 0) | (data.yield_rate > 1)):
        raise ValueError("Yields must be fractions between 0 and 1.")
    if any(data.annual_tuition <= 0):
        raise ValueError("Annual tuition and fees must be positive.")
    p = deepcopy(settings)
    supplied_pools = p.get("applicant_pools", {})
    if not isinstance(supplied_pools, dict) or set(supplied_pools) != set(GROUPS):
        raise ValueError("applicant_pools must give one original count for IM, IF, OM, and OF.")
    pools = {}
    for g, raw in supplied_pools.items():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{g} total_applicants must be a nonnegative whole number.") from None
        if not math.isfinite(value) or value < 0 or value % 1:
            raise ValueError(f"{g} total_applicants must be a nonnegative whole number.")
        pools[g] = int(value)
    p["applicant_pools"] = pools
    for key in ("beds", "program_seats"):
        value = float(p[key])
        if not math.isfinite(value) or value < 0 or value % 1:
            raise ValueError(f"{key} must be a nonnegative whole number.")
        p[key] = int(value)
    for key in ("waitlist_share", "minimum_in_state_share_per_tier",
                "female_share_lower_per_tier", "female_share_upper_per_tier"):
        value = float(p[key])
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} must be a fraction between 0 and 1.")
        p[key] = value
    if p["female_share_lower_per_tier"] > p["female_share_upper_per_tier"]:
        raise ValueError("Female share lower bound exceeds the upper bound.")
    for key in ("minimum_expected_enrollment",):
        value = float(p.get(key, 0))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be nonnegative.")
        p[key] = value
    indexed = data.set_index(["group", "tier"])
    wait = {g: int((Decimal(str(pools[g])) * Decimal(str(p["waitlist_share"])))
                   .quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for g in GROUPS}
    return indexed, p, pools, wait


def build(data, p, pools, wait, env, continuous=False, proportional=False):
    m = gp.Model("admissions", env=env)
    m.Params.TimeLimit = 20
    m.Params.MIPGap = 1e-4
    m.Params.Threads = 2
    m.Params.DualReductions = 0
    a = m.addVars(GROUPS, TIERS, lb=0, vtype=GRB.CONTINUOUS if continuous else GRB.INTEGER,
                  name="admit")
    kind = GRB.CONTINUOUS if continuous else GRB.INTEGER
    ga_pool = m.addVars(GROUPS, lb=0, vtype=kind, name="ga_consideration_pool")
    denied = m.addVars(GROUPS, lb=0, vtype=kind, name="denied")
    for g in GROUPS:
        m.addConstr(ga_pool[g] == pools[g] - a[g,"DA"], name=f"ga_pool_after_da_{g}")
        m.addConstr(a[g,"GA"] + wait[g] + denied[g] == ga_pool[g], name=f"ga_allocation_{g}")
        gender = "male" if g in ("IM", "OM") else "female"
        for t in TIERS:
            # Redundant with lb=0, but named explicitly for formulation review.
            m.addConstr(a[g,t] >= 0, name=f"nonnegative_{gender}_{g}_{t}")
    enrolled = {(g,t): float(data.loc[(g,t), "yield_rate"]) * a[g,t]
                for g in GROUPS for t in TIERS}
    total = gp.quicksum(enrolled.values())
    m.addConstr(total <= p["beds"], name="beds")
    m.addConstr(gp.quicksum(enrolled[g,"DA"] for g in GROUPS) <= p["program_seats"],
                name="program_seats")
    if p["minimum_expected_enrollment"] > 0:
        m.addConstr(total >= p["minimum_expected_enrollment"], name="enrollment_minimum")
    for t in TIERS:
        n = gp.quicksum(enrolled[g,t] for g in GROUPS)
        m.addConstr(enrolled["IM",t] + enrolled["IF",t] >=
                    p["minimum_in_state_share_per_tier"] * n, name=f"in_state_{t}")
        female = enrolled["IF",t] + enrolled["OF",t]
        male = enrolled["IM",t] + enrolled["OM",t]
        m.addConstr(male >= 0, name=f"nonnegative_male_enrollment_{t}")
        m.addConstr(female >= 0, name=f"nonnegative_female_enrollment_{t}")
        m.addConstr(female >= p["female_share_lower_per_tier"] * n, name=f"female_min_{t}")
        m.addConstr(female <= p["female_share_upper_per_tier"] * n, name=f"female_max_{t}")
    if proportional:
        # Same admission fraction per tier across all available group pools,
        # allowing one applicant of rounding either way; DA/GA mix is optimized.
        frac = m.addVars(TIERS, lb=0, ub=1, name="common_admit_fraction")
        m.addConstr(frac.sum() <= 1)
        for g in GROUPS:
            for t in TIERS:
                target = (pools[g] - wait[g]) * frac[t]
                m.addConstr(a[g,t] >= target - 1)
                m.addConstr(a[g,t] <= target + 1)
    m.setObjective(gp.quicksum(float(data.loc[(g,t),"annual_tuition"]) * enrolled[g,t]
                               for g in GROUPS for t in TIERS), GRB.MAXIMIZE)
    return m, a


def audit(data, p, pools, wait, counts):
    """Independent business-rule checks, using returned counts rather than solver slacks."""
    rows = []
    def check(name, actual, relation, bound, tol=1e-6):
        passed = actual <= bound + tol if relation == "<=" else actual >= bound - tol
        rows.append(dict(rule=name, actual=actual, relation=relation, bound=bound,
                         passed=bool(passed)))
    e = {(g,t): counts[g,t]*float(data.loc[(g,t),"yield_rate"])
         for g in GROUPS for t in TIERS}
    for g in GROUPS:
        check(f"{g} applicant pool", sum(counts[g,t] for t in TIERS), "<=", pools[g]-wait[g])
        ga_pool = pools[g] - counts[g,"DA"]
        check(f"{g} GA consideration pool nonnegative", ga_pool, ">=", 0)
        check(f"{g} GA offers plus waitlist fit remaining pool", counts[g,"GA"]+wait[g], "<=", ga_pool)
        check(f"{g} denied nonnegative", ga_pool-counts[g,"GA"]-wait[g], ">=", 0)
        for t in TIERS:
            check(f"{g}/{t} nonnegative", counts[g,t], ">=", 0)
            check(f"{g}/{t} integer error", abs(counts[g,t]-round(counts[g,t])), "<=", 1e-6)
    check("Beds", sum(e.values()), "<=", p["beds"])
    check("Program seats", sum(e[g,"DA"] for g in GROUPS), "<=", p["program_seats"])
    check("Minimum expected enrollment", sum(e.values()), ">=", p["minimum_expected_enrollment"])
    for t in TIERS:
        n = sum(e[g,t] for g in GROUPS)
        check(f"{t} male expected enrollment nonnegative", e["IM",t]+e["OM",t], ">=", 0)
        check(f"{t} female expected enrollment nonnegative", e["IF",t]+e["OF",t], ">=", 0)
        check(f"{t} in-state", e["IM",t]+e["IF",t], ">=", p["minimum_in_state_share_per_tier"]*n)
        check(f"{t} female lower", e["IF",t]+e["OF",t], ">=", p["female_share_lower_per_tier"]*n)
        check(f"{t} female upper", e["IF",t]+e["OF",t], "<=", p["female_share_upper_per_tier"]*n)
    return pd.DataFrame(rows)


def solve(frame, settings, diagnostics=True):
    data,p,pools,wait = validate(frame, settings)
    result = dict(ok=False, status="", optimal=False, conflicts=[], warnings=[])
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 0)
        env.start()
        with build(data,p,pools,wait,env)[0] as m:
            # Variables are retrieved by name so the model's lifetime is explicit.
            m.optimize()
            result.update(status={GRB.OPTIMAL:"Optimal", GRB.INFEASIBLE:"Infeasible",
                GRB.TIME_LIMIT:"Time limit", GRB.INTERRUPTED:"Interrupted"}.get(m.Status,str(m.Status)),
                optimal=m.Status==GRB.OPTIMAL, runtime=m.Runtime)
            if not m.SolCount:
                if m.Status==GRB.INFEASIBLE:
                    m.computeIIS()
                    result["conflicts"]=[c.ConstrName for c in m.getConstrs() if c.IISConstr]
                return result
            counts={(g,t):m.getVarByName(f"admit[{g},{t}]").X for g in GROUPS for t in TIERS}
            checks=audit(data,p,pools,wait,counts)
            if not checks.passed.all():
                result.update(status="Solution failed independent feasibility checks", checks=checks)
                return result
            plan=[]; detail=[]
            for g in GROUPS:
                for t in TIERS:
                    admitted=int(round(counts[g,t])); rate=float(data.loc[(g,t),"yield_rate"])
                    tuition=float(data.loc[(g,t),"annual_tuition"])
                    detail.append(dict(group=g,tier=t,admitted=admitted,yield_rate=rate,
                        expected_enrolled=admitted*rate,annual_tuition_and_fees=tuition,
                        expected_receipts=admitted*rate*tuition))
                plan.append(dict(group=g,total_applicants=pools[g],
                    da_offers=int(round(counts[g,"DA"])),
                    ga_consideration_pool=pools[g]-int(round(counts[g,"DA"])),
                    ga_offers=int(round(counts[g,"GA"])),
                    waitlisted=wait[g],denied=pools[g]-wait[g]-int(round(sum(counts[g,t] for t in TIERS)))))
            detail=pd.DataFrame(detail)
            by_tier=[]
            for t in TIERS:
                selected=detail[detail.tier==t];n=selected.expected_enrolled.sum()
                by_tier.append(dict(tier=t,expected_enrolled=n,
                    in_state_share=selected[selected.group.isin(["IM","IF"])].expected_enrolled.sum()/n if n else None,
                    female_share=selected[selected.group.isin(["IF","OF"])].expected_enrolled.sum()/n if n else None))
            result.update(ok=True,plan=pd.DataFrame(plan),detail=detail,checks=checks,
                composition=pd.DataFrame(by_tier),revenue=float(detail.expected_receipts.sum()),
                expected_enrollment=float(detail.expected_enrolled.sum()),
                da_enrollment=float(detail[detail.tier=="DA"].expected_enrolled.sum()),
                mip_gap=m.MIPGap,objective_upper_bound=m.ObjBound)
        if result["expected_enrollment"] < 1e-8:
            result["warnings"].append("The optimum admits nobody. Composition constraints allow an empty class; review inputs or set a minimum enrollment.")
        if diagnostics:
            with build(data,p,pools,wait,env,continuous=True)[0] as lp:
                lp.optimize()
                if lp.Status==GRB.OPTIMAL:
                    result["lp_bound"]=lp.ObjVal
                    result["lp_gap_pct"]=100*(lp.ObjVal-result["revenue"])/max(1,abs(lp.ObjVal))
                    result["capacity_duals"]=pd.DataFrame([
                        dict(capacity=name,lp_marginal_receipts=lp.getConstrByName(name).Pi,
                             slack=lp.getConstrByName(name).Slack) for name in ("beds","program_seats")])
            changes=[]
            for key in ("beds","program_seats","minimum_in_state_share_per_tier"):
                q=deepcopy(p);q[key]+= .01 if key.startswith("minimum") else 1
                if key.startswith("minimum") and q[key] > 1:
                    continue
                other=solve(frame,q,diagnostics=False)
                changes.append(dict(change=("In-state minimum +1 percentage point" if key.startswith("minimum") else key+" +1"),
                    status=other["status"],delta_receipts=other.get("revenue",float("nan"))-result["revenue"],
                    delta_lower_bound=other.get("revenue",float("nan"))-result["objective_upper_bound"],
                    delta_upper_bound=other.get("objective_upper_bound",float("nan"))-result["revenue"],
                    optimal=other["optimal"]))
            result["discrete_changes"]=pd.DataFrame(changes)
            with build(data,p,pools,wait,env,proportional=True)[0] as base:
                base.optimize()
                result["benchmark_status"]="Optimal" if base.Status==GRB.OPTIMAL else str(base.Status)
                if base.Status==GRB.OPTIMAL:
                    result["benchmark_revenue"]=base.ObjVal
    return result


if __name__=="__main__":
    frame,settings=defaults();r=solve(frame,settings)
    print(r["status"])
    if r["ok"]:
        print(r["plan"].to_string(index=False))
        print(f"Expected annual tuition-and-fee receipts: ${r['revenue']:,.2f}")
        print(f"Expected enrolled: {r['expected_enrollment']:.2f}")
    else: print(r["conflicts"])
