"""Independent model and app checks for the admissions planner."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import unittest
import pandas as pd
from admissions_model import defaults, solve, GROUPS, TIERS


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.data,self.p=defaults()

    def test_default_checks_and_accounting(self):
        r=solve(self.data,self.p)
        self.assertTrue(r["optimal"])
        self.assertTrue(r["checks"].passed.all())
        self.assertEqual(int(r["plan"].total_applicants.sum()),15000)
        self.assertEqual(int(r["plan"].waitlisted.sum()),1500)
        self.assertTrue((r["plan"][["da_offers","ga_offers","waitlisted","denied"]].sum(axis=1)==r["plan"].total_applicants).all())
        self.assertTrue((r["plan"].ga_consideration_pool==r["plan"].total_applicants-r["plan"].da_offers).all())
        self.assertTrue((r["plan"][["ga_offers","waitlisted","denied"]].sum(axis=1)==r["plan"].ga_consideration_pool).all())
        self.assertGreaterEqual(r["lp_bound"]+1e-5,r["revenue"])
        self.assertLessEqual(r["benchmark_revenue"],r["revenue"]+max(1e-5,r["lp_bound"]*1e-4))

    def test_tiny_instance_against_exhaustive_enumeration(self):
        self.p["applicant_pools"]={g:1 for g in GROUPS}
        self.data["yield_rate"]=1.
        self.data["annual_tuition"]=self.data.tier.map({"GA":10.,"DA":20.})
        self.p.update(beds=2,program_seats=1,waitlist_share=0.,
            minimum_in_state_share_per_tier=.5,female_share_lower_per_tier=0.,
            female_share_upper_per_tier=1.)
        best=0
        for choices in product([None,"GA","DA"],repeat=4):
            if sum(t is not None for t in choices)>2 or choices.count("DA")>1:continue
            valid=True
            for tier in TIERS:
                total=choices.count(tier)
                residents=sum(choices[i]==tier for i in [0,1])
                if residents<.5*total:valid=False
            if valid:best=max(best,sum({None:0,"GA":10,"DA":20}[t] for t in choices))
        r=solve(self.data,self.p,False)
        self.assertEqual(best,30)
        self.assertAlmostEqual(r["revenue"],best)

    def test_infeasible_target(self):
        self.p.update(beds=1,minimum_expected_enrollment=2)
        r=solve(self.data,self.p)
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"],"Infeasible")
        self.assertTrue(r["conflicts"])

    def test_empty_class_is_explained(self):
        self.p.update(beds=0)
        r=solve(self.data,self.p,False)
        self.assertTrue(r["ok"])
        self.assertEqual(r["expected_enrollment"],0)
        self.assertTrue(r["warnings"])

    def test_missing_tuition_and_negative_pool_rejected(self):
        bad=self.data.copy();bad.loc[0,"annual_tuition"]=float("nan")
        with self.assertRaises(ValueError):solve(bad,self.p)
        self.p["applicant_pools"]["IM"]=-1
        with self.assertRaises(ValueError):solve(self.data,self.p)

    def test_zero_gender_pools_and_no_separate_ga_applicants(self):
        self.assertNotIn("applicants",self.data.columns)
        self.p["applicant_pools"]={"IM":0,"IF":100,"OM":0,"OF":100}
        self.p.update(female_share_lower_per_tier=0.,female_share_upper_per_tier=1.)
        r=solve(self.data,self.p,False)
        self.assertTrue(r["ok"])
        self.assertTrue((r["plan"].select_dtypes(include="number")>=0).all().all())
        self.assertEqual(r["plan"].set_index("group").loc[["IM","OM"],["da_offers","ga_offers"]].to_numpy().sum(),0)

    def test_named_nonnegativity_constraints(self):
        import gurobipy as gp
        from admissions_model import validate,build
        data,p,pools,wait=validate(self.data,self.p)
        with gp.Env(empty=True) as env:
            env.setParam("OutputFlag",0);env.start()
            with build(data,p,pools,wait,env)[0] as m:
                m.update()
                for g in GROUPS:
                    gender="male" if g in ("IM","OM") else "female"
                    for t in TIERS:
                        self.assertIsNotNone(m.getConstrByName(f"nonnegative_{gender}_{g}_{t}"))
                for t in TIERS:
                    self.assertIsNotNone(m.getConstrByName(f"nonnegative_male_enrollment_{t}"))
                    self.assertIsNotNone(m.getConstrByName(f"nonnegative_female_enrollment_{t}"))

    def test_yield_and_gender_bounds_rejected(self):
        bad=self.data.copy();bad.loc[0,"yield_rate"]=1.2
        with self.assertRaises(ValueError):solve(bad,self.p)
        self.p.update(female_share_lower_per_tier=.8,female_share_upper_per_tier=.2)
        with self.assertRaises(ValueError):solve(self.data,self.p)

    def test_capacity_monotonicity(self):
        base=solve(self.data,self.p,False)
        self.p["beds"]+=200
        relaxed=solve(self.data,self.p,False)
        self.assertGreaterEqual(relaxed["revenue"]+1e-5,base["revenue"])

    def test_synthetic_dataset_flow_and_backend_compatibility(self):
        import json
        from admissions_model import validate
        folder=Path(__file__).parent / "data/synthetic_admissions_dataset_v2"
        raw=pd.read_csv(folder / "synthetic_applicants.csv")
        flows=pd.read_csv(folder / "synthetic_applicant_flow_by_cycle.csv")
        self.assertEqual(len(raw),75000)
        self.assertEqual(raw.applicant_id.nunique(),75000)
        self.assertTrue((raw.dataset_type=="SYNTHETIC").all())
        self.assertTrue((raw.applied_to_DA==1).all())
        self.assertTrue((raw.da_offered+raw.ga_considered==1).all())
        self.assertTrue((raw.ga_offered<=raw.ga_considered).all())
        grouped=raw.groupby(["cycle_id","group"])
        for row in flows.itertuples():
            members=grouped.get_group((row.cycle_id,row.group))
            self.assertEqual(len(members),row.total_applicants)
            self.assertEqual(int(members.ga_considered.sum()),row.ga_consideration_pool)
            self.assertEqual(row.total_applicants,row.da_offers+row.ga_offers+row.waitlisted+row.denied)
            self.assertEqual(row.ga_consideration_pool,row.total_applicants-row.da_offers)
        frame=pd.read_csv(folder / "synthetic_model_inputs.csv")
        settings=json.loads((folder / "synthetic_scenario_settings.json").read_text())
        _,_,pools,_=validate(frame,settings)
        self.assertEqual(sum(pools.values()),15000)
        self.assertNotIn("applicants",frame.columns)


class InterfaceTests(unittest.TestCase):
    def test_submit_save_and_sweep(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_file(str(Path(__file__).with_name("app.py")),default_timeout=60).run()
        self.assertFalse(at.exception)
        next(b for b in at.button if b.label=="Solve admissions plan").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Optimal" in s.value for s in at.success))
        next(b for b in at.button if b.label=="Save this scenario for comparison").click().run()
        self.assertEqual(len(at.session_state["saved"]),1)
        next(b for b in at.button if b.label=="Run three capacity scenarios").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["sweep"][1]),3)
        next(n for n in at.number_input if n.label=="Minimum expected enrollment (optional)").set_value(2000.)
        next(b for b in at.button if b.label=="Solve admissions plan").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Infeasible" in e.value for e in at.error))


if __name__=="__main__":unittest.main()
