"""Reusable normalized priority scoring and semantic deduplication."""
import math


def rank(candidates,scale,designation):
    """Impact-sensitive scoring and semantic grouping; never pad the result."""
    weights={'financial_impact_score':.35,'severity_score':.25,'urgency_score':.20,'actionability_score':.15,'confidence_score':.05}
    boosts={'ASM':{'employee_underperformance','vacancy_coverage'},'RSM':{'employee_underperformance','discount_efficiency','vacancy_coverage'},'HOD':{'product_mix','vacancy_coverage','stock_risk'}}
    for c in candidates:
        c['financial_impact_score']=min(100,100*math.sqrt(c['financial_impact']/max(scale,1)))
        if c['type'] in boosts.get(designation,set()): c['actionability_score']=min(100,c['actionability_score']+10)
        c['priority_score']=round(sum(c[k]*v for k,v in weights.items()),1)
    ordered=sorted(candidates,key=lambda c:(-c['priority_score'],-c['financial_impact'],c['type']))
    chosen=[]; seen=set()
    for c in ordered:
        if c['confidence_score']<60 or c['priority_score']<30 or c['dedup_group'] in seen: continue
        seen.add(c['dedup_group']); chosen.append(c)
        if len(chosen)==5: break
    return chosen

