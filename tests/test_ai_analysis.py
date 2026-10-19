"""Synthetic fixtures exercise edge cases only; production reads PostgreSQL."""
import unittest
from services.ai_analysis.engine import analyze, rank


def row(code='A', actual=70000, target=100000, **extra):
    r=dict(id=code,name='Product '+code,position='P1',group='G1',actual=actual,target=target,units=70,
           unit_target=100,tp=100000,tp_target=120000,discounts=5000,regular_budget=6000,
           additional_budget=0,positive=max(actual or 0,0),returns=0)
    r.update(extra); return r


def context(rows, **extra):
    c=dict(rows=rows,filters=dict(designation='MIO',employee='Employee',product='All',product_group='All'),
           stock=[],staff=[('P1','Employee','MIO','ASM1')],customers=[],history=[],targets_available=True)
    c.update(extra);return c


def types(c): return {x['type'] for x in analyze(c)['insights']}


class InsightTests(unittest.TestCase):
    def test_empty_is_not_padded(self): self.assertEqual(analyze(context([]))['insights'],[])
    def test_no_period_is_not_zero_sales(self): self.assertEqual(analyze(context([row()],period_available=False))['insights'],[])
    def test_missing_actual_excludes_gap(self): self.assertNotIn('sales_target',types(context([row(actual=None)])))
    def test_missing_targets_excludes_achievement(self):
        t=types(context([row(target=None,unit_target=None)],targets_available=False))
        self.assertFalse(t & {'sales_target','product_gap','unit_volume','growth_driver'})
    def test_individual_no_subordinate_ranking(self):
        self.assertNotIn('employee_underperformance',types(context([row()])))
    def test_gap_dedup(self):
        cards=analyze(context([row(),row('B',10000,40000)]))['insights']
        self.assertEqual(sum(c['dedup_group']=='target_gap' for c in cards),1)
    def test_gap_driver_uses_money(self):
        cards=analyze(context([row('Small',25000,50000),row('Big',2400000,3000000)]))['insights']
        gap=next(c for c in cards if c['dedup_group']=='target_gap')
        self.assertIn('Big',gap['summary'])
    def test_volume_distinct(self): self.assertIn('unit_volume',types(context([row(units=40)])))
    def test_regular_discount(self): self.assertIn('discount_efficiency',types(context([row(discounts=15000)])))
    def test_additional_discount(self): self.assertIn('discount_efficiency',types(context([row(bonus_discount=15000)])))
    def test_positive(self):
        cards=analyze(context([row(actual=140000,positive=140000)]))['insights']
        self.assertTrue(any(c['severity']=='positive' for c in cards));self.assertIn('growth_driver',{c['type'] for c in cards})
    def test_returns(self): self.assertIn('return_impact',types(context([row(returns=20000,positive=90000)])))
    def test_history_gap_suppressed(self):
        self.assertNotIn('sales_momentum',types(context([row()],history=[('Jan',120000),('Feb',None),('Mar',80000)])))
    def test_consecutive_history(self):
        self.assertIn('sales_momentum',types(context([row()],history=[('Jan',120000),('Feb',100000),('Mar',80000)])))
    def test_no_stock_match(self): self.assertFalse(types(context([row()])) & {'stock_risk','stock_constrained','recovery_opportunity'})
    def test_stock_constraint(self):
        c=context([row()],stock=[('A','Depot',5,100,2,1000,'2026-07-31')])
        self.assertIn('stock_constrained',types(c))
    def test_stock_recovery(self):
        c=context([row()],stock=[('A','Depot',500,100,25,50000,'2026-07-31')])
        self.assertIn('recovery_opportunity',types(c))
    def test_excess_stock(self):
        c=context([row()],stock=[('A','Depot',500,100,100,50000,'2026-07-31')])
        self.assertIn('stock_risk',types(c))
    def test_invalid_stock_not_used_for_opportunity(self):
        t=types(context([row()],stock=[('A','Depot',500,100,0,50000,'2026-07-31')]))
        self.assertIn('data_quality',t); self.assertNotIn('stock_constrained',t)
    def test_customer_concentration(self):
        customers=[('C1','Account One',40000,0),('C2','Two',15000,0),('C3','Three',10000,0),('C4','Four',5000,0)]
        self.assertIn('customer_concentration',types(context([row()],customers=customers)))
    def test_vacancy_and_manager_rollup(self):
        c=context([row(position='P1'),row('B',20000,100000,position='P2')],staff=[('P1','VACANT','MIO','ASM1'),('P2','Two','SPO','ASM1')])
        c['filters']['designation']='ASM'
        t=types(c);self.assertIn('vacancy_coverage',t);self.assertIn('employee_underperformance',t)
    def test_quality(self): self.assertIn('data_quality',types(context([row(code='#N/A')])) )
    def test_scores_and_limit(self):
        c=context([row(returns=10000,units=40,discounts=20000),row('B',140000,100000),row('C',5000,50000)])
        cards=analyze(c)['insights'];self.assertLessEqual(len(cards),5)
        self.assertEqual([x['priority_score'] for x in cards],sorted([x['priority_score'] for x in cards],reverse=True))
        self.assertEqual(len({x['dedup_group'] for x in cards}),len(cards))
        for card in cards:
            for key in ('severity_score','financial_impact_score','urgency_score','actionability_score','confidence_score','priority_score'):
                self.assertTrue(0<=card[key]<=100)
    def test_financial_impact_outranks_percent_only(self):
        def candidate(kind,impact,severity):
            return dict(type=kind,dedup_group=kind,financial_impact=impact,severity_score=severity,urgency_score=70,actionability_score=85,confidence_score=95)
        result=rank([candidate('small',25000,90),candidate('big',600000,65)],3050000,'MIO')
        self.assertEqual(result[0]['type'],'big')
    def test_product_card_explains_lost_buyers(self):
        c=context([row(actual=70000)],prior_month='August,26',product_customers=[
            ('A','C1','Lost account','August,26',40000),
            ('A','C2','Retained account','August,26',70000),
            ('A','C2','Retained account','September,26',70000),
        ])
        card=analyze(c)['product_performance'][0]
        self.assertIn('Customers stopped ordering this product',
                      [finding['title'] for finding in card['diagnosis']['blockers']])
        self.assertEqual(card['diagnosis']['bridge']['lost'],-40000)
    def test_product_finding_keeps_all_names_for_expansion(self):
        c=context([row(actual=70000)], prior_month='August,26', product_customers=[
            ('A', f'C{i}', f'Lost account {i}', 'August,26', 40000 - i)
            for i in range(4)
        ])
        card=analyze(c)['product_performance'][0]
        finding=next(x for x in card['diagnosis']['blockers'] if x['title']=='Customers stopped ordering this product')
        self.assertEqual([x['name'] for x in finding['related_items']],
                         ['Lost account 0', 'Lost account 1', 'Lost account 2', 'Lost account 3'])
        self.assertNotIn('+1 more', finding['detail'])

    def test_related_names_are_bounded_and_report_full_count(self):
        c=context([row(actual=70000)], prior_month='August,26', product_customers=[
            ('A', f'C{i}', f'Lost account {i}', 'August,26', 40000 - i)
            for i in range(30)
        ])
        card=analyze(c)['product_performance'][0]
        finding=next(x for x in card['diagnosis']['blockers'] if x['title']=='Customers stopped ordering this product')
        self.assertEqual(len(finding['related_items']), 20)
        self.assertEqual(finding['related_total'], 30)
    def test_product_card_explains_growth(self):
        c=context([row(actual=140000,positive=140000,units=110)],prior_month='August,26',product_customers=[
            ('A','C1','Existing','August,26',60000),
            ('A','C1','Existing','September,26',90000),
            ('A','C2','New buyer','September,26',50000),
        ])
        card=analyze(c)['product_performance'][0]
        self.assertTrue(card['diagnosis']['strengths'])
        self.assertIn('New buyers are adding product sales',
                      [finding['title'] for finding in card['diagnosis']['strengths']])
        self.assertFalse(card['diagnosis']['blockers'])
    def test_product_stock_requires_matched_depot(self):
        c=context([row()],product_depot=[('A','Depot',70000)],
                  depot_stock=[('A','Depot',5,10,3)])
        card=analyze(c)['product_performance'][0]
        self.assertIn('Low shared depot stock may limit orders',
                      [finding['title'] for finding in card['diagnosis']['blockers']])
        c['product_depot']=[('A','Other depot',70000)]
        card=analyze(c)['product_performance'][0]
        self.assertNotIn('Low shared depot stock may limit orders',
                         [finding['title'] for finding in card['diagnosis']['blockers']])

    def test_employee_pagination_returns_page_metadata(self):
        result = analyze(context([
            row('A', 140000, 100000, position='P1'), row('B', 90000, 100000, position='P2'), row('C', 70000, 100000, position='P3')
        ]), limit=2, offset=1)
        self.assertEqual(len(result['employee_performance']), 2)
        self.assertEqual(result['employee_total'], 3)
        self.assertEqual(result['page_offset'], 1)
        self.assertFalse(result['has_more_employees'])

    def test_employee_pagination_filters_band_before_page(self):
        result = analyze(context([
            row('A', 140000, 100000, position='P1'), row('B', 90000, 100000, position='P2'), row('C', 50000, 100000, position='P3')
        ]), limit=10, band='low')
        self.assertEqual(result['employee_total'], 1)
        self.assertEqual(len(result['employee_performance']), 1)
        self.assertEqual(result['employee_performance'][0]['employee_id'], 'P3')

if __name__=='__main__': unittest.main()
