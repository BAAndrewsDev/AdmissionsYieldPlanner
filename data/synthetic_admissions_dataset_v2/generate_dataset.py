"""Generate explicitly synthetic admissions records. Uses only Python standard library."""
from pathlib import Path
import csv, json, random, math, zipfile

ROOT = Path(__file__).resolve().parent
SEED = 20261117
GROUPS = [('IM','in_state','male',3000,.35),('IF','in_state','female',3750,.26),
          ('OM','out_of_state','male',3750,.08),('OF','out_of_state','female',4500,.06)]
TUITION = {('in_state','GA'):15014,('in_state','DA'):21254,
           ('out_of_state','GA'):46058,('out_of_state','DA'):50166}
FACTORS = [.90,1.05,.95,1.10,1.00]


def write_csv(name, records):
    with (ROOT/name).open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]))
        writer.writeheader();writer.writerows(records)


def main():
    rng=random.Random(SEED)
    records=[]; summaries=[]; flows=[]
    for cycle,factor in enumerate(FACTORS,1):
        for group,residency,gender,pool,ga_yield in GROUPS:
            # Exact 25% DA, 45% GA, 10% waitlist, remainder denied; half-up rounding.
            da=int(math.floor(pool*.25+.5));ga=int(math.floor(pool*.45+.5))
            waiting=int(math.floor(pool*.10+.5))
            decisions=['DA']*da+['GA']*ga+['WAITLIST']*waiting+['DENIED']*(pool-da-ga-waiting)
            rng.shuffle(decisions)
            # One shared multiplier per group/cycle, applied to both tiers.
            group_factor=rng.uniform(.95,1.05)
            cycle_rows=[]
            for number,decision in enumerate(decisions,1):
                tier=decision if decision in ['GA','DA'] else ''
                prob=min(.99,max(.01,ga_yield*(1.5 if tier=='DA' else 1)*factor*group_factor)) if tier else None
                enrolled=int(rng.random()<prob) if tier else 0
                tuition=TUITION[residency,tier] if tier else None
                row=dict(dataset_type='SYNTHETIC',cycle_id=f'SIM_{cycle:02}',
                    applicant_id=f'SYN-C{cycle:02}-{group}-{number:05}',group=group,
                    residency=residency,gender=gender,applied_to_DA=1,
                    da_offered=int(decision=='DA'),ga_considered=int(decision!='DA'),
                    ga_offered=int(decision=='GA'),admission_decision=decision,
                    admission_tier=tier,enrollment_probability=round(prob,8) if tier else '',
                    enrolled=enrolled,annual_tuition_and_fees=tuition if tier else '',
                    simulated_annual_receipts=enrolled*tuition if tier else 0,
                    tuition_reference_year='2026-27',cycle_yield_multiplier=factor,
                    group_cycle_multiplier=round(group_factor,8))
                records.append(row);cycle_rows.append(row)
            flows.append(dict(dataset_type='SYNTHETIC',cycle_id=f'SIM_{cycle:02}',
                group=group,residency=residency,gender=gender,total_applicants=pool,
                da_offers=da,ga_consideration_pool=pool-da,ga_offers=ga,
                waitlisted=waiting,denied=pool-da-ga-waiting))
            for tier in ['GA','DA']:
                admitted=[r for r in cycle_rows if r['admission_tier']==tier]
                n=len(admitted);n_enrolled=sum(r['enrolled'] for r in admitted)
                summaries.append(dict(dataset_type='SYNTHETIC',cycle_id=f'SIM_{cycle:02}',
                    group=group,residency=residency,gender=gender,tier=tier,
                    admitted=n,enrolled=n_enrolled,
                    simulated_yield=n_enrolled/n,
                    assumed_yield_probability=ga_yield*(1.5 if tier=='DA' else 1),
                    generating_yield_probability=admitted[0]['enrollment_probability'],
                    annual_tuition=TUITION[residency,tier],tuition_reference_year='2026-27'))
    pooled=[];model_rows=[]
    for group,residency,gender,pool,base in GROUPS:
        for tier in ['GA','DA']:
            selected=[s for s in summaries if s['group']==group and s['tier']==tier]
            admits=sum(s['admitted'] for s in selected);enrolled=sum(s['enrolled'] for s in selected)
            pooled.append(dict(dataset_type='SYNTHETIC',group=group,residency=residency,gender=gender,
                tier=tier,cycles=5,
                admitted=admits,enrolled=enrolled,simulated_yield=enrolled/admits,
                annual_tuition=TUITION[residency,tier],tuition_reference_year='2026-27'))
            model_rows.append(dict(group=group,residency=residency,gender=gender,tier=tier,
                yield_rate=enrolled/admits,annual_tuition=TUITION[residency,tier],
                input_status='SYNTHETIC_POOLED_YIELDS_assumed_applicants_and_tier_mapping'))
    assert len(records)==75000 and len({r['applicant_id'] for r in records})==75000
    assert len(summaries)==40 and len(pooled)==8
    for cycle in range(1,6):
        current=[r for r in records if r['cycle_id']==f'SIM_{cycle:02}']
        assert len(current)==15000
        assert sum(r['admission_decision']=='WAITLIST' for r in current)==1500
    for r in records:
        assert not r['enrolled'] or r['admission_tier'] in ['GA','DA']
        assert r['simulated_annual_receipts']==(r['enrolled']*r['annual_tuition_and_fees'] if r['admission_tier'] else 0)
    for s in summaries:
        raw=[r for r in records if r['cycle_id']==s['cycle_id'] and r['group']==s['group'] and r['admission_tier']==s['tier']]
        assert len(raw)==s['admitted'] and sum(r['enrolled'] for r in raw)==s['enrolled']
    # Validate the applicant flow independently from the tier summaries.
    assert len(flows)==20
    for f in flows:
        assert f['total_applicants']==f['da_offers']+f['ga_consideration_pool']
        assert f['ga_consideration_pool']==f['ga_offers']+f['waitlisted']+f['denied']
        assert all(f[k]>=0 for k in ['total_applicants','da_offers','ga_consideration_pool','ga_offers','waitlisted','denied'])
        raw=[r for r in records if r['cycle_id']==f['cycle_id'] and r['group']==f['group']]
        assert sum(r['applied_to_DA'] for r in raw)==f['total_applicants']
        assert sum(r['ga_considered'] for r in raw)==f['ga_consideration_pool']
        assert sum(r['da_offered'] for r in raw)==f['da_offers']
        assert sum(r['ga_offered'] for r in raw)==f['ga_offers']
    assert all(r['da_offered']+r['ga_considered']==1 for r in records)
    assert all(r['ga_offered']<=r['ga_considered'] for r in records)
    pool_rows=[dict(group=g,residency=r,gender=s,total_applicants=n) for g,r,s,n,y in GROUPS]
    write_csv('synthetic_applicant_pools.csv',pool_rows)
    write_csv('synthetic_applicant_flow_by_cycle.csv',flows)
    write_csv('synthetic_applicants.csv',records)
    write_csv('synthetic_yields_by_cycle.csv',summaries)
    write_csv('synthetic_yields_pooled.csv',pooled)
    write_csv('synthetic_model_inputs.csv',model_rows)
    assumptions=dict(dataset_type='SYNTHETIC',seed=SEED,cycles=5,applicants_per_cycle=15000,
        cycle_labels='SIM_01 to SIM_05; not actual academic years',
        cohort_scope='Each applicant ID is a separate simulated person within one cycle; no personal records are used',
        applicant_flow='All apply to DA. Those without DA offers are considered for GA; GA offers, waitlists and denials partition the remaining pool.',
        optimization_semantics='Descriptive staged flow; no DA-priority optimization or ranking is implied.',
        schema_version=2,
        pools=[dict(group=g,residency=r,gender=s,total_applicants=n,base_GA_yield=y) for g,r,s,n,y in GROUPS],
        decision_shares=dict(DA=.25,GA=.45,WAITLIST=.10,DENIED=.20),rounding='half-up, remainder assigned to denied',
        DA_yield_multiplier=1.5,cycle_yield_multipliers=FACTORS,
        group_cycle_yield_multiplier='Independent Uniform(0.95,1.05), shared by both tiers',
        enrollment_model='Independent Bernoulli draws conditional on cycle/group yield; waitlisted/denied do not enroll',
        yield_probability_bounds=[.01,.99],
        tuition_reference=dict(academic_year='2026-27',source_url='https://www.colorado.edu/bursar/costs/undergraduate',
            source_verified_date='2026-11-14',resident_GA=15014,resident_DA=21254,nonresident_GA=46058,nonresident_DA=50166,
            mapping='GA=Base and DA=Business/Tier 4 is hypothetical, not a verified admission policy',
            constant_across_simulations=True,resident_basis='Student share after COF; fees included'),
        limitations=['No empirical admissions calibration; not historical CU records.',
            'More simulated rows do not establish yield accuracy.',
            'Plans are not optimized and are not constrained to fit 1000 beds or 700 program seats.',
            'No academic merit or individual admission ranking is modeled.',
            'Bernoulli independence is an assumption; unmodeled shared shocks may change risk.'])
    (ROOT/'generation_assumptions.json').write_text(json.dumps(assumptions,indent=2)+'\n',encoding='utf-8')
    settings=dict(scenario_name='SYNTHETIC pooled yields',dataset_type='SYNTHETIC',
        applicant_pools={g:n for g,r,s,n,y in GROUPS},beds=1000,program_seats=700,
        waitlist_share=.10,minimum_in_state_share_per_tier=.55,
        female_share_lower_per_tier=.45,female_share_upper_per_tier=.55,
        minimum_expected_enrollment=0,
        note='Settings use 15,000 original applicants once. GA consideration counts are solver outputs.')
    (ROOT/'synthetic_scenario_settings.json').write_text(json.dumps(settings,indent=2)+'\n',encoding='utf-8')
    files=['synthetic_applicants.csv' ,'synthetic_yields_by_cycle.csv','synthetic_yields_pooled.csv',
           'synthetic_model_inputs.csv','synthetic_applicant_pools.csv','synthetic_applicant_flow_by_cycle.csv',
           'synthetic_scenario_settings.json','generation_assumptions.json','README.md','generate_dataset.py']
    with zipfile.ZipFile(ROOT.parent/'synthetic_admissions_dataset_v2.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in files:z.write(ROOT/name,'synthetic_admissions_dataset_v2/'+name)
    print('Validated: 75,000 records; 20 balanced applicant flows; 40 yield summaries; 8 tier inputs; 4 original pools.')
    print('Per-cycle actual simulated enrollment:',{f'SIM_{c:02}':sum(r['enrolled'] for r in records if r['cycle_id']==f'SIM_{c:02}') for c in range(1,6)})

if __name__=='__main__':main()
