"""Streamlit interface for the educational admissions planning model."""
from copy import deepcopy
import json
import pandas as pd
import streamlit as st
import gurobipy as gp
from admissions_model import defaults, solve, GROUPS

st.set_page_config(page_title="Admissions Yield Planner", layout="wide")
st.title("Admissions Yield Planner")
st.write("Choose an aggregate admissions plan that maximizes expected annual tuition-and-fee receipts under capacity and composition targets.")
st.caption("Educational scenario, not CU Boulder's actual admissions process. Applicant counts, yields, capacities, and targets are assumptions. No individual applicant decisions are made.")
data, initial = defaults()
# A running browser may still hold results from the old repeated-pool schema.
if "last" in st.session_state:
    previous_result = st.session_state["last"][0]
    if previous_result.get("ok") and "ga_consideration_pool" not in previous_result["plan"]:
        st.session_state.pop("last", None)
        st.session_state.pop("sweep", None)
        st.info("The applicant-pool layout has changed. Please solve again with the updated inputs.")

with st.sidebar:
    st.header("Scenario assumptions")
    if st.button("Reset inputs and results"):
        st.session_state.clear()
        st.rerun()

with st.form("scenario"):
    left,right=st.columns([2,1])
    with left:
        st.subheader("Original applicant pools")
        st.caption("Everyone starts in the DA applicant pool. Enter each group's total once. GA consideration pool = total applicants − DA offers; it is calculated after solving, not entered separately.")
        pool_inputs=st.data_editor(pd.DataFrame([
            dict(group=g,total_applicants=initial["applicant_pools"][g]) for g in GROUPS]),
            disabled=["group"],hide_index=True,width="stretch",
            column_config={"total_applicants":st.column_config.NumberColumn(min_value=0,step=1)},
            key="original_pools")
        st.subheader("Assumed yield rates")
        st.caption("Yields are fractions: 0.35 means 35%.")
        edited=st.data_editor(data[["group","tier","yield_rate"]],
            disabled=["group","tier"], hide_index=True, width="stretch",
            column_config={"yield_rate":st.column_config.NumberColumn(min_value=0.,max_value=1.,step=.005,format="%.3f")})
        st.caption("GA offers, waitlists, and denials share the remaining pool after DA offers. Both offer counts are optimized jointly; no separate DA-priority objective is imposed.")
        st.subheader("Published 2026–27 annual tuition and fees")
        st.caption("GA uses Base; DA uses Business/Tier 4. That admission-to-program mapping is a model assumption. Resident figures are the student share after COF; fees are included. Housing, aid, and COF receipts are excluded from the objective.")
        rates=[]
        for residency,label in [("in_state","In-state"),("out_of_state","Out-of-state")]:
            cols=st.columns(2)
            for col,tier in zip(cols,["GA","DA"]):
                default=int(data[(data.residency==residency)&(data.tier==tier)].annual_tuition.iloc[0])
                value=col.number_input(f"{label} {tier} annual USD",min_value=1,value=default,step=100)
                rates.append((residency,tier,value))
        same_rates=st.checkbox("Use base tuition for both admission tiers",value=False)
        st.caption("Edited amounts are scenario overrides; the published source values remain in the data files.")
    with right:
        st.subheader("Capacity and policy settings")
        p=deepcopy(initial)
        p["beds"]=st.number_input("Beds",min_value=0,value=1000,step=50)
        p["program_seats"]=st.number_input("Direct Admit program seats",min_value=0,value=700,step=50)
        p["waitlist_share"]=st.slider("Waitlist share (%)",0,100,10)/100
        p["minimum_in_state_share_per_tier"]=st.slider("Minimum in-state share per tier (%)",0,100,55)/100
        band=st.slider("Female share band per tier (%)",0,100,(45,55))
        p["female_share_lower_per_tier"],p["female_share_upper_per_tier"]=[v/100 for v in band]
        p["minimum_expected_enrollment"]=st.number_input("Minimum expected enrollment (optional)",min_value=0.,value=0.,step=50.)
        st.caption("Composition targets apply to expected enrollment within each tier. Zero students satisfy share constraints. Set a minimum if an empty class is unacceptable.")
        label=st.text_input("Scenario name",value="Default planning scenario")
    submitted=st.form_submit_button("Solve admissions plan",type="primary")

st.link_button("CU Boulder 2026–27 source", "https://www.colorado.edu/bursar/costs/undergraduate")
if submitted:
    try:
        frame=data.copy()
        p["applicant_pools"]=dict(zip(pool_inputs.group,pool_inputs.total_applicants))
        frame["yield_rate"]=edited.yield_rate.to_numpy()
        rate_map={(res,t):v for res,t,v in rates}
        frame["annual_tuition"]=[rate_map[(row.residency,"GA" if same_rates else row.tier)] for row in frame.itertuples()]
        with st.spinner("Solving Gurobi model and checking the plan…"):
            r=solve(frame,p)
        st.session_state["last"]=(r,frame,p,label)
        st.session_state.pop("sweep",None)
    except (ValueError,KeyError,TypeError,gp.GurobiError) as exc:
        st.session_state.pop("last",None)
        st.error(f"Could not solve: {exc}")

if "last" not in st.session_state:
    st.info("Set your inputs and select Solve admissions plan. No results are precomputed.")
    st.stop()
r,frame,p,label=st.session_state["last"]
st.subheader(f"Results for {label}")
st.caption("Results use the last submitted inputs. Submit again after editing the form.")
if not r["ok"]:
    st.error("Solver status: "+r["status"]+". No recommended plan is available.")
    if r["conflicts"]: st.write("Conflicting constraints (one IIS):",r["conflicts"])
    st.stop()
if r["optimal"]: st.success(f"Optimal within solver tolerance (target gap 0.01%) · solve time {r['runtime']:.3f}s")
else: st.warning(f"{r['status']}: feasible incumbent, not a certified optimum. Gap {r['mip_gap']:.2%}.")
for warning in r["warnings"]:st.warning(warning)
cols=st.columns(4)
cols[0].metric("Expected annual receipts",f"${r['revenue']:,.0f}")
cols[1].metric("Expected enrolled / beds",f"{r['expected_enrollment']:,.2f} / {p['beds']:,}")
cols[2].metric("DA expected enrolled / seats",f"{r['da_enrollment']:,.2f} / {p['program_seats']:,}")
cols[3].metric("Applicants (unique pools)",f"{sum(p['applicant_pools'].values()):,.0f}")
plan_tab,limits_tab,compare_tab,sweep_tab,about_tab=st.tabs(["Admissions plan","Limits and verification","Compare scenarios","Capacity sweep","Model and assumptions"])
with plan_tab:
    st.dataframe(r["plan"],hide_index=True,width="stretch")
    st.caption("GA consideration pool overlaps the original pool. Do not add it to total applicants. DA offers + GA offers + waitlisted + denied = total applicants.")
    st.bar_chart(r["plan"].set_index("group")[["da_offers","ga_offers"]])
    st.dataframe(r["detail"],hide_index=True,width="stretch")
    st.download_button("Download plan CSV",r["plan"].to_csv(index=False),"admissions_plan.csv","text/csv")
    st.download_button("Download submitted inputs CSV",frame.to_csv(index=False),"scenario_inputs.csv","text/csv")
    pools_export=pd.DataFrame([dict(group=g,total_applicants=n) for g,n in p["applicant_pools"].items()])
    st.download_button("Download original applicant pools CSV",pools_export.to_csv(index=False),"applicant_pools.csv","text/csv")
    st.download_button("Download submitted settings",json.dumps(p,indent=2),"scenario_settings.json","application/json")
with limits_tab:
    st.write("Expected composition by tier (a share is blank if the tier is empty)")
    st.dataframe(r["composition"],hide_index=True)
    st.dataframe(r["checks"],hide_index=True,width="stretch")
    if "capacity_duals" in r:
        st.write(f"LP relaxation upper bound: ${r['lp_bound']:,.2f}; gap from the current integer plan: {r['lp_gap_pct']:.4f}%.")
        st.dataframe(r["capacity_duals"],hide_index=True)
        st.caption("LP duals are local continuous-model sensitivities, not guaranteed integer-model marginal values. A small objective gap does not validate them.")
    if "discrete_changes" in r:
        st.write("Actual re-solves of the integer model")
        st.dataframe(r["discrete_changes"],hide_index=True)
        st.caption("Delta bounds use solver objective bounds from both runs. Differences inside that interval are unresolved at the solver tolerance; the displayed delta is not an exact marginal value.")
    if "benchmark_revenue" in r:
        st.write(f"Proportional-admissions benchmark receipts: ${r['benchmark_revenue']:,.0f}; difference: ${r['revenue']-r['benchmark_revenue']:,.0f}.")
        st.caption("Benchmark uses a common admit fraction across groups within each tier (±1 applicant for rounding), optimizing only the tier mix while enforcing the same policies.")
    else:st.caption("No certified benchmark optimum was available.")
with compare_tab:
    if st.button("Save this scenario for comparison"):
        st.session_state.setdefault("saved",[]).append(dict(scenario=label,receipts=r["revenue"],
            expected_enrolled=r["expected_enrollment"],beds=p["beds"],program_seats=p["program_seats"],
            in_state_minimum=p["minimum_in_state_share_per_tier"],status=r["status"]))
    if st.session_state.get("saved"):st.dataframe(pd.DataFrame(st.session_state.saved),hide_index=True)
    st.caption("Saved rows are snapshots from completed solves. They do not update when you change inputs.")
with sweep_tab:
    chosen=st.selectbox("Vary capacity",["beds","program_seats"])
    if st.button("Run three capacity scenarios"):
        scenarios=[]
        try:
            for scale in [.8,1.,1.2]:
                q=deepcopy(p);q[chosen]=int(round(p[chosen]*scale))
                other=solve(frame,q,diagnostics=False)
                scenarios.append(dict(capacity=q[chosen],status=other["status"],
                    receipts=other.get("revenue"),expected_enrolled=other.get("expected_enrollment")))
            st.session_state["sweep"]=(chosen,pd.DataFrame(scenarios))
        except (ValueError,gp.GurobiError) as exc:st.error(str(exc))
    if "sweep" in st.session_state:
        which,table=st.session_state.sweep
        st.write(f"Completed sweep of {which}")
        st.dataframe(table,hide_index=True)
        st.line_chart(table.set_index("capacity")[["receipts"]])
with about_tab:
    st.latex(r"\max \sum_{g,t} T_{g,t}y_{g,t}a_{g,t}")
    st.write("For each group: GA consideration pool = total applicants − DA offers. GA offers + waitlisted + denied = GA consideration pool. All offers, consideration pools, and denied counts are nonnegative integers. Male and female expected enrollment is explicitly constrained nonnegative. Both tiers are optimized jointly, not in two priority rounds.")
    st.write("All counts, yields, capacities, and targets are illustrative assumptions. The tuition amounts are published 2026–27 full-time annual tuition and mandatory fees; mapping DA to Business and GA to Base is assumed. Scholarships, retention, COF funding, institutional costs, and housing revenue are not modeled.")
    st.warning("Expected enrollment constraints do not prevent actual over-enrollment. This is a classroom planning exercise, not an individual admissions system or a verified representation of university policy.")
