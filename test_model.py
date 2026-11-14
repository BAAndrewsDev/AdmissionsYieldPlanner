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
        self.assertEqual(int(r["plan"].applicants.sum()),15000)
        self.assertEqual(int(r["plan"].waitlisted.sum()),1500)
        self.assertTrue((r["plan"][["direct_admits","general_admits","waitlisted","denied"]].sum(axis=1)==r["plan"].applicants).all())
        self.assertGreaterEqual(r["lp_bound"]+1e-5,r["revenue"])
        self.assertLessEqual(r["benchmark_revenue"],r["revenue"]+max(1e-5,r["lp_bound"]*1e-4))

    def test_tiny_instance_against_exhaustive_enumeration(self):
        self.data["applicants"]=1
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

    def test_missing_tuition_and_duplicate_pool_rejected(self):
        bad=self.data.copy();bad.loc[0,"annual_tuition"]=float("nan")
        with self.assertRaises(ValueError):solve(bad,self.p)
        bad=self.data.copy();bad.loc[0,"applicants"]+=1
        with self.assertRaises(ValueError):solve(bad,self.p)

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
