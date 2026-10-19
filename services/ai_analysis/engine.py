"""Deterministic candidate generation. Money is PKR; ratios use matched denominators."""
from collections import defaultdict
import math
from .insight_ranker import rank
from .diagnosis import build_index, benchmarks, diagnose
from .product_diagnosis import build_product_index, diagnose_product


def money(n):
    return 'PKR ' + (f'{n/1e6:,.2f}M' if abs(n)>=1e6 else f'{n/1e3:,.1f}K' if abs(n)>=1000 else f'{n:,.0f}')


def pct(n): return f'{n:.1f}%'
def ratio(a,b): return a/b*100 if a is not None and b is not None and b>0 else None

def total(rows,key):
    if key in {'actual', 'units'} and any(r.get(key) is None for r in rows): return None
    values=[r[key] for r in rows if r.get(key) is not None]
    return sum(values) if values else None


def aggregate(rows,key):
    groups=defaultdict(list)
    for row in rows: groups[row.get(key)].append(row)
    result=[]
    for identity, members in groups.items():
        name=next((r['name'] for r in members if r.get('name') and r['name']!=r.get('id')),identity or 'Unmapped product')
        item=dict(id=identity,name=name,members=members)
        for k in ('actual','units','target','unit_target','tp','discounts','positive','returns','tp_target','regular_budget','additional_budget'):
            item[k]=total(members,k)
        item['gap']=max(0,item['target']-item['actual']) if item['target'] is not None and item['actual'] is not None else 0
        item['achievement']=ratio(item['actual'],item['target'])
        result.append(item)
    return result


def analyze(context, limit=None, offset=0, band='all'):
    rows=context['rows']; filters=context['filters']; designation=filters['designation']
    if context.get('period_available') is False:
        return dict(insights=[],candidate_count=0,analysis_types=15,targets_available=context['targets_available'],filters=filters,period_incomplete=context.get('partial_period',False),message='Sales data is not loaded for this reporting period. No performance findings have been inferred.')
    products=aggregate(rows,'id'); positions=aggregate(rows,'position')
    actual=total(rows,'actual'); target=total(rows,'target'); units=total(rows,'units'); unit_target=total(rows,'unit_target')
    ach=ratio(actual,target); actual=actual or 0; scale=max(target or 0,total(rows,'positive') or 0,1)
    material=max(1000,scale*.01); uach=ratio(units,unit_target)
    gap=max(0,(target or 0)-actual); candidates=[]
    product_gaps=sorted([p for p in products if p['gap']>=material],key=lambda p:-p['gap'])
    drivers=product_gaps[:2]; names=', '.join(p['name'] for p in drivers)
    gross_gap=sum(p['gap'] for p in products)
    def add(kind,category,title,summary,action,impact,severity=60,status=None,metrics=(),group=None,confidence=95,urgency=65):
        if not math.isfinite(impact) or impact<0: return
        candidates.append(dict(type=kind,category=category,title=title,summary=summary,recommended_action=action,
            severity=status or ('critical' if severity>=85 else 'high' if severity>=65 else 'medium'),
            financial_impact=round(impact,2),severity_score=min(100,max(0,severity)),urgency_score=urgency,
            actionability_score=85,confidence_score=confidence,achievement_pct=round(ach,1) if ach is not None else None,metrics=[dict(label=k,value=str(v)) for k,v in metrics],
            entity='product' if filters.get('product','All')!='All' else 'employee' if filters['employee']!='All' else 'scope',
            entity_id=filters.get('product') if filters.get('product','All')!='All' else filters['employee'],dedup_group=group or kind))
    period_note=' Against the full-month target; this period is incomplete.' if context.get('partial_period') else ''
    # 1 and 4 share a diagnosis group: show the most informative gap, not two restatements.
    if ach is not None and ach<95 and gap>=material:
        parent_share=ratio(gap,context.get('parent_gap'))
        detail=(f' This is {pct(parent_share)} of the immediate reporting team?s gross shortfall.' if parent_share is not None else '')
        detail+=f' {names} account for {pct(sum(p["gap"] for p in drivers)/gross_gap*100)} of gross product shortfall.' if drivers else ''
        add('sales_target','Sales performance','Major Target Shortfall',f'Net sales achievement is {pct(ach)}, leaving {money(gap)} below target.'+detail+period_note,
            f'Build a recovery plan for {names or "the selected scope"}; verify orders against the remaining {money(gap)} target.',gap,min(95,45+(100-ach)*.6),
            metrics=[('Achievement',pct(ach)),('Target gap',money(gap)),('Actual',money(actual))],group='target_gap',urgency=45 if context.get('partial_period') else 80)
    if product_gaps:
        p=product_gaps[0]; share=p['gap']/gross_gap*100
        if share>=25:
            add('product_gap','Product performance','Largest Product Gap',f'{p["name"]} contributes {pct(share)} of gross product shortfall: {money(p["gap"])} at {pct(p["achievement"])} achievement.'+period_note,
                f'Review unfilled orders and coverage for {p["name"]}; its gap is {money(p["gap"])}.',p['gap'],75,
                metrics=[('Product gap',money(p['gap'])),('Share of shortfall',pct(share))],group='target_gap')
    # 2: volume adds a distinct diagnosis only when materially worse than value.
    if uach is not None and ach is not None and uach<85 and ach-uach>=8 and gap>=material:
        weak=sorted([p for p in products if (ratio(p['units'],p['unit_target']) or 0)<85 and (p['unit_target'] or 0)>0],key=lambda p:-p['gap'])[:2]
        add('unit_volume','Volume','Volume Behind Value',f'Unit achievement is {pct(uach)} versus {pct(ach)} in value; volume trails by {ach-uach:.1f} percentage points.',
            f'Prioritize unit orders and productive calls for {", ".join(p["name"] for p in weak) or names}; close the {max(0,unit_target-(units or 0)):,.0f}-unit gap.',gap*.7,75,
            metrics=[('Units achieved',pct(uach)),('Value achieved',pct(ach))])
    # 3: compare regular discounts with regular budget, and bonus with no invented proxy.
    matched=[r for r in rows if r.get('tp_target') and r.get('regular_budget') is not None and r.get('tp') is not None and r.get('discounts') is not None]
    tp=total(matched,'tp'); ttp=total(matched,'tp_target')
    discount=ratio(abs(total(matched,'discounts') or 0),tp); budget=ratio(total(matched,'regular_budget'),ttp)
    if discount is not None and budget is not None and ach is not None:
        delta=discount-budget; leakage=max(0,delta/100*tp)
        if delta>=1 and leakage>=material:
            critical=ach<90
            culprit=max(matched,key=lambda r:abs(r['discounts'])-(r['regular_budget']/r['tp_target'])*(r['tp'] or 0))
            add('discount_efficiency','Discount','Discount Leakage' if critical else 'Growth at Higher Discount',
                f'Regular discount is {pct(discount)} versus {pct(budget)} planned ({delta:.1f} percentage points above budget), with value achievement at {pct(ach)}.',
                f'Review regular discount approvals on {culprit["name"]} before repeating this pricing; estimated excess discount is {money(leakage)}.',leakage,85 if critical else 55,
                metrics=[('Actual discount',pct(discount)),('Budget',pct(budget)),('Excess',money(leakage))])
        elif ach>=105 and delta<=0 and actual>=material:
            add('discount_efficiency','Discount','Efficient Sales Delivery',f'Sales achieve {pct(ach)} while regular discount stays at {pct(discount)}, within the {pct(budget)} budget.',
                f'Preserve the current regular discount ceiling of {pct(budget)} when extending orders for the highest-selling products.',max(actual-(target or 0),0),60,'positive',
                [('Achievement',pct(ach)),('Discount',pct(discount)),('Budget',pct(budget))])
        elif ach<85 and delta<=-1 and gap>=material:
            add('discount_efficiency','Discount','Unused Pricing Headroom',f'Regular discount is {budget-discount:.1f} points below plan while sales achieve {pct(ach)}.',
                f'Test a budget-compliant offer on {names or "targeted products"} and measure incremental units before extending it.',min(gap,(budget-discount)/100*tp),50,'opportunity',
                [('Achievement',pct(ach)),('Budget headroom',f'{budget-discount:.1f} pp')],confidence=75)
    bonus_rows=[r for r in rows if r.get('tp_target') and r.get('additional_budget') is not None and r.get('bonus_discount') is not None and r.get('tp') is not None]
    bonus_tp=total(bonus_rows,'tp')
    bonus_rate=ratio(abs(total(bonus_rows,'bonus_discount') or 0),bonus_tp)
    bonus_budget=ratio(total(bonus_rows,'additional_budget'),total(bonus_rows,'tp_target'))
    if bonus_rate is not None and bonus_budget is not None and bonus_rate-bonus_budget>=1:
        excess=(bonus_rate-bonus_budget)/100*bonus_tp
        if excess>=material:
            culprit=max(bonus_rows,key=lambda r:abs(r['bonus_discount'])-r['additional_budget']/r['tp_target']*r['tp'])
            add('discount_efficiency','Discount','Additional Discount Over Budget',
                f'Bonus/additional discount is {pct(bonus_rate)} against {pct(bonus_budget)} planned; excess discount is {money(excess)}.'+(f' Unit achievement is {pct(uach)}.' if uach is not None else ''),
                f'Review bonus discount on {culprit["name"]}; require evidence of incremental orders before renewing the offer.',excess,85 if uach is not None and uach<85 else 60,
                metrics=[('Additional discount',pct(bonus_rate)),('Budget',pct(bonus_budget)),('Excess',money(excess))])
    # 6: only consecutive complete months; a missing month cannot create a drop.
    history=context['history']; series=[]
    for m,v in reversed(history):
        if v is None: break
        series.insert(0,(m,v))
    if len(series)>=3 and series[-2][1]>0:
        change=(series[-1][1]/series[-2][1]-1)*100; impact=abs(series[-1][1]-series[-2][1])
        if abs(change)>=10 and impact>=material:
            rising=change>0; consecutive=all((b[1]>a[1])==rising and b[1]!=a[1] for a,b in zip(series,series[1:]))
            add('sales_momentum','Momentum','Growing Sales Momentum' if rising else 'Declining Sales Momentum',
                f'{series[-1][0]} sales are {pct(abs(change))} {"above" if rising else "below"} {series[-2][0]}.'+(f' Direction is consistent across {len(series)} completed months.' if consecutive else ''),
                f'Compare orders in {series[-1][0]} with {series[-2][0]} for {names or "the selected product portfolio"}; '+('protect the accounts driving this increase.' if rising else f'identify the lost orders behind the {money(impact)} decline.'),
                impact,65 if rising else 80,'positive' if rising else None,[('Monthly change',f'{change:+.1f}%'),('Completed months',len(series))])
    # 7: returns are kept separate from net target achievement.
    returns=total(rows,'returns') or 0; positive=total(rows,'positive') or 0
    if returns>=material and positive>0 and returns/positive>=.02:
        leaders=sorted(products,key=lambda p:-(p['returns'] or 0))[:2]
        customer=max(context['customers'],key=lambda c:float(c[3] or 0),default=None)
        responsible=(customer[1] or customer[0]) if customer and customer[3] else ', '.join(p['name'] for p in leaders)
        add('return_impact','Returns','Return Impact',f'Return/reversal lines total {money(returns)}, equivalent to {pct(returns/positive*100)} of positive sales. {", ".join(p["name"] for p in leaders)} account for {pct(sum(p["returns"] or 0 for p in leaders)/returns*100)} of this value.',
            f'Investigate return reasons and credit notes for {responsible} before further replenishment.',returns,85,metrics=[('Reversals',money(returns)),('Return rate',pct(returns/positive*100))],urgency=90)
    # 8/9/5: depot evidence is explicitly shared, never allocated to an employee.
    pmap={p['id']:p for p in products}; recovery=[]; inventory_issues=[]
    for code,depot,closing,avg,days,value,date in context['stock']:
        p=pmap.get(code)
        if not p or closing is None or avg is None or days is None: continue
        closing=float(closing); avg=float(avg); days=float(days); exposure=float(value or 0)
        if closing<0 or days<0 or (closing>0 and avg>0 and days==0):
            inventory_issues.append((p,depot,exposure)); continue
        if days<12 and avg>0 and (p['actual'] or 0)>0:
            constrained=p['gap']>=material and p['achievement'] is not None and p['achievement']>=70
            impact=min(p['gap'],p['actual']) if constrained else (p['actual'] or 0)*min(1,(12-days)/30)
            if impact>=material:
                add('stock_constrained' if constrained else 'stock_risk','Inventory','Stock-Constrained Opportunity' if constrained else 'Low Depot Stock',
                    f'{p["name"]} has {days:.0f} inventory days at shared depot {depot} as of {date}. '+(f'{money(p["gap"])} of target remains exposed; this is not a lost-sales forecast.' if constrained else 'Current depot coverage is below 12 days.'),
                    f'Confirm allocation and replenish {p["name"]} at {depot} before accepting additional orders.',impact,85,
                    metrics=[('Depot cover',f'{days:.0f} days'),('Shared closing units',f'{closing:,.0f}')],group='stock:'+str(code),confidence=75,urgency=95)
        elif closing>0 and (avg==0 or days>=90):
            if exposure>=material:
                add('stock_risk','Inventory','Dead Stock Exposure' if avg==0 else 'Excess Depot Stock',f'{p["name"]} has {closing:,.0f} units at shared depot {depot}, '+('with zero recorded average sales.' if avg==0 else f'covering {days:.0f} days.'),
                    f'Check expiry dates and transfer demand for {p["name"]} at {depot} before placing more stock.',exposure,70,
                    metrics=[('Depot stock value',money(exposure)),('Closing units',f'{closing:,.0f}')],group='stock:'+str(code),confidence=75)
        elif 15<=days<=45 and closing>0 and p['gap']>=material and p['achievement'] is not None and p['achievement']>=70:
            recovery.append(p)
    recovery=list({p['id']:p for p in recovery}.values())
    if recovery:
        recovery=sorted(recovery,key=lambda p:-p['gap'])[:3]; opportunity=sum(p['gap'] for p in recovery)
        add('recovery_opportunity','Recovery','Stock-Supported Recovery',f'{", ".join(p["name"] for p in recovery)} carry {money(opportunity)} of target gap and have matched shared depots with 15–45 inventory days. Recovery depends on confirmed allocation and demand.',
            f'Confirm depot allocation, then seek orders for {recovery[0]["name"]} first; its remaining target is {money(recovery[0]["gap"])}.',opportunity,70,'opportunity',
            [('Target opportunity',money(opportunity)),('Products',len(recovery))],confidence=70)
    # 10: direct-level manager comparison rolls each child hierarchy up once.
    staff={s[0]:s for s in context['staff']}; children=defaultdict(list)
    for pos,name,role,parent in context['staff']: children[parent].append(pos)
    levels={'ASM':{'SPO','MIO'},'RSM':{'ASM'},'HOD':{'RSM'},'ALL':{'RSM'}}
    ppositions={p['id']:p for p in positions}; teams=[]
    for code,s in staff.items():
        if s[2] not in levels.get(designation,set()): continue
        pending=[code]; seen=set()
        while pending:
            node=pending.pop()
            if node in seen: continue
            seen.add(node); pending.extend(children[node])
        members=[ppositions[k] for k in seen if k in ppositions]
        t=sum(p['target'] or 0 for p in members); a=sum(p['actual'] or 0 for p in members)
        if t>0: teams.append((s[1] or code,code,max(0,t-a),a/t*100))
    weak=sorted([t for t in teams if t[2]>=material and t[3]<90],key=lambda t:-t[2])[:3]
    teamgap=sum(t[2] for t in teams)
    if len(teams)>=2 and weak and teamgap>0:
        impact=sum(t[2] for t in weak)
        add('employee_underperformance','Team coverage','Concentrated Team Shortfall',f'{len(weak)} reporting teams/positions contribute {pct(impact/teamgap*100)} of peer shortfall. {weak[0][0]} ({weak[0][1]}) is the largest contributor at {money(weak[0][2])}.',
            f'Review the product and order recovery plan with {weak[0][0]} for position {weak[0][1]}.',impact,80,
            metrics=[('Combined shortfall',money(impact)),('Largest contributor achieved',pct(weak[0][3]))])
    # 11: positive candidates compete on actual financial contribution.
    winners=sorted([p for p in products if p['achievement'] is not None and p['achievement']>=110 and (p['actual']-p['target'])>=material],key=lambda p:-(p['actual']-p['target']))
    if winners:
        p=winners[0]; excess=p['actual']-p['target']
        add('growth_driver','Growth','Strong Growth Driver',f'{p["name"]} achieves {pct(p["achievement"])} of target, adding {money(excess)} above plan.',
            f'Protect order fulfilment for {p["name"]} and review its successful customer orders for replication across the selected scope.',excess,65,'positive',
            [('Achievement',pct(p['achievement'])),('Above target',money(excess))])
    # 12: use names/explicit vacancy flags, not lack of sales as a vacancy proxy.
    vacant=[p for p in positions if p['id'] in staff and (not (staff[p['id']][1] or '').strip() or any(w in staff[p['id']][1].upper() for w in ('VACANT','UNMANNED'))) and (p['target'] or 0)>0]
    if vacant and designation not in {'MIO','SPO'}:
        exposure=sum(p['target'] for p in vacant)
        if exposure>=material:
            codes=', '.join(str(p['id']) for p in sorted(vacant,key=lambda p:-p['target'])[:3])
            add('vacancy_coverage','Workforce','Vacant Territory Exposure',f'{len(vacant)} vacant positions carry {money(exposure)} in selected-month targets. Affected positions include {codes}.',
                f'Assign temporary coverage for {codes} while filling these vacancies.',exposure,80,
                metrics=[('Vacant positions',len(vacant)),('Target exposure',money(exposure))])
    # 13: scoped quality checks; no claim about positions outside the selected hierarchy.
    invalid=lambda v:not str(v or '').strip() or str(v).upper() in {'#N/A','N/A','NULL'} or 'UNMAPPED' in str(v).upper()
    quality=[r for r in rows if invalid(r['id']) or invalid(r['position']) or (context['targets_available'] and r.get('target') is None and (r.get('actual') or 0)>0)]
    exposure=sum(abs(r.get('actual') or 0) for r in quality)
    if exposure>=material:
        add('data_quality','Data quality','Unreconciled Sales Mapping',f'{money(exposure)} of scoped sales ({pct(exposure/scale*100)} of the scope baseline) have invalid identifiers or no matching product-position target.',
            f'Reconcile product {quality[0]["id"] or "missing code"} at position {quality[0]["position"] or "missing code"} against the staff and target masters before judging achievement.',exposure,40 if exposure/scale<.1 else 70,
            metrics=[('Affected sales',money(exposure)),('Product-position records',len(quality))],urgency=40)
    if context.get('orphan_sales',0)>=material or context.get('orphan_targets',0)>=material:
        orphan_sales=context.get('orphan_sales',0); orphan_targets=context.get('orphan_targets',0)
        impact=orphan_sales+orphan_targets
        add('data_quality','Data quality','Unassigned National Records',f'{money(orphan_sales)} of sales-line value and {money(orphan_targets)} of target sit outside the staff hierarchy because their position codes have no staff-master match.',
            'Reconcile the unmatched sales and target position codes with staff_master before allocating these national totals to teams.',impact,70 if impact/scale>=.1 else 40,
            metrics=[('Unassigned sales value',money(orphan_sales)),('Unassigned target',money(orphan_targets))],urgency=40)
    if inventory_issues:
        p,depot,exposure=max(inventory_issues,key=lambda x:x[2])
        if exposure>=material:
            add('data_quality','Data quality','Invalid Inventory Metrics',f'{p["name"]} at {depot} has inconsistent stock or inventory-day values.',
                f'Reconcile closing stock and average sales for {p["name"]} at {depot} before allocating stock.',exposure,45,
                metrics=[('Affected stock value',money(exposure)),('Depot',depot)],urgency=40)
    # 14: denominator uses all positive sales, including anonymous customer records.
    customers=sorted([c for c in context['customers'] if c[0] and float(c[2] or 0)>0],key=lambda c:-float(c[2]))
    top=customers[:3]; share=sum(float(c[2]) for c in top)/positive*100 if positive>0 else 0
    if customers and positive>=material and share>=55:
        impact=sum(float(c[2]) for c in top)
        add('customer_concentration','Customers','Customer Dependency',f'Top {len(top)} customers account for {pct(share)} of positive sales. {top[0][1] or top[0][0]} is the largest account.',
            f'Protect the order schedule for {top[0][1] or top[0][0]} and build repeat orders with {(customers[3][1] or customers[3][0]) if len(customers)>3 else 'additional accounts in the selected territory'} to broaden the customer base.',impact,65,
            metrics=[('Top customer share',pct(float(top[0][2])/positive*100)),('Top three share',pct(share))])
    # 15: portfolio imbalance combines concentration with neglected targeted products.
    groups=aggregate(rows,'group'); lead=max(groups,key=lambda g:g['positive'] or 0,default=None)
    neglected=[p for p in products if p['achievement'] is not None and p['achievement']<50 and p['gap']>=material]
    if lead and positive>0 and (lead['positive'] or 0)/positive>=.65 and len(neglected)>=2:
        impact=sum(p['gap'] for p in neglected); neglected.sort(key=lambda p:-p['gap'])
        add('product_mix','Portfolio','Unbalanced Product Portfolio',f'{pct(lead["positive"]/positive*100)} of positive sales comes from {lead["id"] or "an unclassified group"}, while {len(neglected)} targeted products achieve less than 50%.',
            f'Add {neglected[0]["name"]} and {neglected[1]["name"]} to order plans; their combined gap is {money(sum(p["gap"] for p in neglected[:2]))}.',impact,70,
            metrics=[('Dominant group',pct(lead['positive']/positive*100)),('Neglected product gap',money(impact))],group='target_gap')
    # Product / SKU mode is intentionally a product lens, not an individual
    # product picker.  Keep portfolio, SKU, demand, returns and inventory
    # findings, while excluding people-management findings from this view.
    if filters.get("mode") == "product":
        people_only = {"employee_underperformance", "vacancy_coverage", "customer_concentration"}
        candidates = [candidate for candidate in candidates if candidate["type"] not in people_only]
    insights=rank(candidates,scale,designation)
    staff_by_position = {row[0]: {'employee': row[1], 'designation': row[2]} for row in context.get('staff', [])}
    def card_kpis(record, target_record, achievement_value, entity_label):
        previous = record.get('previous') or 0
        actual_value = record.get('actual') or 0
        discount_pct = round(abs(record.get('discount') or 0) / record['tp'] * 100, 1) if record.get('tp') else None
        budget_value = (target_record.get('regular_budget') or 0) + (target_record.get('additional_budget') or 0)
        budget_pct = round(budget_value / target_record['tp_target'] * 100, 1) if target_record.get('tp_target') else None
        variance = round(discount_pct - budget_pct, 1) if discount_pct is not None and budget_pct is not None else None
        if variance is None:
            insight = f'Discount is {pct(discount_pct)} of TP sales; no matched discount budget is available.' if discount_pct is not None else 'Discount comparison is unavailable because TP sales are missing.'
        elif variance > 0 and achievement_value < 70:
            insight = f'Discount is {variance:.1f} pp above budget while {entity_label} achievement is below 70%; review discount-led orders and recovery actions.'
        elif variance > 0:
            insight = f'Discount is {variance:.1f} pp above budget; verify that the higher discount is supporting sustainable sales delivery.'
        elif achievement_value >= 100:
            insight = f'Achievement is above target while discount is {abs(variance):.1f} pp within budget; maintain the current discount discipline.'
        elif achievement_value < 70:
            insight = f'Discount is {abs(variance):.1f} pp below budget but achievement is below 70%; check availability, coverage and demand before increasing discount.'
        else:
            insight = f'Discount is {abs(variance):.1f} pp within budget; focus on closing the remaining sales gap.'
        return dict(
            total_ucc=record.get('ucc', 0),
            previous_sales=previous,
            golm_pct=round((actual_value - previous) / abs(previous) * 100, 1) if previous else None,
            discount_pct=discount_pct, discount_budget_pct=budget_pct, discount_variance_pp=variance,
            ai_insight=insight,
        )
    employee_kpis = context.get('employee_kpis', {})
    product_kpis = context.get('product_kpis', {})
    employee_performance = [
        dict(
            employee=staff_by_position.get(p.get('id'), {}).get('employee') or p.get('id') or 'Unmapped employee',
            employee_id=p.get('id'),
            designation=staff_by_position.get(p.get('id'), {}).get('designation') or designation,
            actual=p.get('actual'), target=p.get('target'),
            achievement_pct=round(p['achievement'], 1),
            **card_kpis(employee_kpis.get(p.get('id'), {}), p, p['achievement'], 'employee'),
        )
        for p in positions if p.get('achievement') is not None
    ]
    # Roll-up designations (ASM/RSM/HOD/DGM/EXEC) need one card per manager,
    # using the NET_SALE_VALUE and target rows of that manager's reporting tree.
    manager_roles = {'ASM', 'RSM', 'HOD', 'DGM', 'EXEC'}
    if designation in manager_roles:
        staff_rows = {row[0]: {'employee': row[1], 'designation': row[2], 'parent': row[3]} for row in context.get('staff', [])}
        rows_by_position = defaultdict(list)
        for row in rows:
            rows_by_position[row.get('position')].append(row)
        children = defaultdict(list)
        for position, staff_row in staff_rows.items():
            if staff_row.get('parent'):
                children[staff_row['parent']].append(position)
        def tree(root):
            found, pending = set(), [root]
            while pending:
                position = pending.pop()
                if position in found: continue
                found.add(position); pending.extend(children.get(position, []))
            return found
        manager_cards = []
        for position, staff_row in staff_rows.items():
            if staff_row.get('designation') != designation: continue
            members = tree(position)
            actual = sum(float(row.get('actual') or 0) for member in members for row in rows_by_position.get(member, []))
            target = sum(float(row.get('target') or 0) for member in members for row in rows_by_position.get(member, []))
            if target <= 0: continue
            kpi = {'ucc': 0, 'actual': 0, 'discount': 0, 'tp': 0, 'previous': 0}
            target_record = {'regular_budget': 0, 'additional_budget': 0, 'tp_target': 0}
            for member in members:
                source = employee_kpis.get(member, {})
                for key in kpi: kpi[key] += source.get(key, 0) or 0
                for row in rows_by_position.get(member, []):
                    target_record['regular_budget'] += float(row.get('regular_budget') or 0)
                    target_record['additional_budget'] += float(row.get('additional_budget') or 0)
                    target_record['tp_target'] += float(row.get('tp_target') or 0)
            achievement_value = actual / target * 100 if target else None
            manager_cards.append(dict(employee=staff_row.get('employee') or position, employee_id=position,
                designation=designation, actual=actual, target=target, achievement_pct=round(achievement_value, 1),
                **card_kpis(kpi, target_record, achievement_value, 'team')))
        employee_performance = manager_cards
    def in_band(card):
        achievement = float(card.get('achievement_pct') or 0)
        return band == 'all' or band == 'high' and achievement >= 100 or band == 'average' and 70 <= achievement < 100 or band == 'low' and achievement < 70

    employee_performance.sort(key=lambda card: float(card.get('achievement_pct') or 0), reverse=True)
    employee_performance = [card for card in employee_performance if in_band(card)]
    employee_total = len(employee_performance)
    if limit is not None:
        employee_page = employee_performance[max(0, offset):max(0, offset) + max(1, limit)]
    else:
        employee_page = employee_performance

    # Root-cause diagnosis: explain WHY each employee/team is high or low, using
    # customer, product, stock, discount and peer evidence rather than restating KPIs.
    diag_index = build_index(context)
    child_map = defaultdict(list)
    for sp, sr in ((r[0], r) for r in context.get('staff', [])):
        if sr[3]: child_map[sr[3]].append(sp)
    def positions_of(code):
        if designation not in manager_roles: return {code}
        found, pending = set(), [code]
        while pending:
            node = pending.pop()
            if node in found: continue
            found.add(node); pending.extend(child_map.get(node, []))
        return found
    diag_bench = benchmarks(employee_performance, positions_of, diag_index)
    for card in employee_page:
        try:
            card['diagnosis'] = diagnose(positions_of(card['employee_id']), diag_index, diag_bench, card)
        except Exception:
            card['diagnosis'] = None  # never let one card break the whole panel
    product_performance = [
        dict(product=p.get('name') or p.get('id') or 'Unmapped product', product_id=p.get('id'),
             actual=p.get('actual'), target=p.get('target'), achievement_pct=round(p['achievement'], 1),
             **card_kpis(product_kpis.get(p.get('id'), {}), p, p['achievement'], 'product'))
        for p in products if p.get('achievement') is not None
    ]
    product_performance.sort(key=lambda card: float(card.get('achievement_pct') or 0), reverse=True)
    product_performance = [card for card in product_performance if in_band(card)]
    product_total = len(product_performance)
    if limit is not None:
        product_page = product_performance[max(0, offset):max(0, offset) + max(1, limit)]
    else:
        product_page = product_performance
    product_index = build_product_index(context)
    for card in product_page:
        try:
            card['diagnosis'] = diagnose_product(card, product_index)
        except Exception:
            card['diagnosis'] = None  # keep other product cards available
    return dict(insights=insights,employee_performance=employee_page,product_performance=product_page,
                employee_total=employee_total,product_total=product_total,
                page_offset=offset,page_limit=limit,has_more_employees=offset + len(employee_page) < employee_total,
                has_more_products=offset + len(product_page) < product_total,
                candidate_count=len(candidates),analysis_types=15,targets_available=context['targets_available'],
                filters=filters,period_incomplete=context.get('partial_period',False),
                message='' if insights else 'No sufficiently supported, material findings for this selection. Broaden the filters or choose a completed reporting period.')
