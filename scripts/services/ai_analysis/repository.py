"""Read-only adapter using the dashboard scope and verified PostgreSQL columns."""
import datetime as dt
from collections import defaultdict


def load_context(query, scope_cte, filters, date, target_fy,
                 resolved_positions=None, reporting_tree_resolver=None,
                 use_summaries=False):
    sfx = date.strftime('%b_%y').lower()
    cte, args = scope_cte(*(filters[k] for k in ('designation', 'region', 'zone', 'subzone', 'territory', 'employee')),
                          team=filters['team'], target_suffix=sfx,
                          resolved_positions=resolved_positions)
    team = filters['team']
    def where(alias, product_col='product_no', group_col='group_on'):
        clauses, values = [], []
        if team != 'COMBINED':
            clauses.append(f"UPPER({alias}.team) LIKE %s")
            values.append('%PHARMA%' if team == 'PHARMA' else 'FAST MOVING CONSUMER GOODS%')
        for col, key in ((product_col, 'product'), (group_col, 'product_group')):
            if filters.get(key, 'All') != 'All':
                clauses.append(f'{alias}.{col} = %s'); values.append(filters[key])
        return ''.join(' AND '+c for c in clauses), values
    sw, sa = where('s')
    tw, ta = where('t', group_col='product_group_on_master')
    month = date.strftime('%B,%y')
    position_product_source = ('public.sales_monthly_position_product_summary'
                               if use_summaries else 'sales_data')
    customer_source = ('public.sales_monthly_customer_summary'
                       if use_summaries else 'sales_data')
    position_source = ('public.sales_monthly_position_summary'
                       if use_summaries else 'sales_data')
    returns_expr = ('COALESCE(SUM(s.return_impact_value),0)' if use_summaries else
                    'SUM(CASE WHEN s.net_sale_value < 0 OR s.net_qty < 0 OR s.net_value < 0 '
                    'THEN ABS(s.net_sale_value) ELSE 0 END)')
    positive_expr = ('COALESCE(SUM(s.positive_net_sale_value),0)' if use_summaries else
                     'SUM(GREATEST(s.net_sale_value,0))')
    value_count_expr = ('SUM(s.net_sale_value_rows)' if use_summaries else
                        'COUNT(s.net_sale_value)')
    units_count_expr = ('SUM(s.net_qty_rows)' if use_summaries else 'COUNT(s.net_qty)')
    tp_column = 's.gross_tp_value' if use_summaries else 's.tp_sale_value'
    sales = query(f'''{cte} SELECT s.position_code, s.product_no, MAX(s.prd_name), MAX(s.group_on),
        SUM(s.net_sale_value), SUM(s.net_qty), SUM({tp_column}), SUM(s.discounts),
        {returns_expr}, {positive_expr}, {value_count_expr}, {units_count_expr}, SUM(s.bonus_discount)
        FROM {position_product_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.position_code,s.product_no
        ORDER BY s.position_code,s.product_no''', args+[month, filters['fy']]+sa)
    columns = {r[0] for r in query("SELECT column_name FROM information_schema.columns WHERE table_name='target_data'", [])}
    available = filters['fy'] == target_fy and 'tgt_net_w_reg_'+sfx in columns
    targets = query(f'''{cte} SELECT t.position_code_2026_27,t.product_no,MAX(t.product_group_on_master),
        SUM(t.tgt_net_w_reg_{sfx}), SUM(t.tgt_unit_{sfx}), SUM(t.tgt_tp_value_{sfx}),
        SUM(t.tgt_reg_disc_value_{sfx}), SUM(t.tgt_add_disc_value_{sfx})
        FROM target_data t WHERE t.position_code_2026_27 IN (SELECT position_code FROM scope) {tw}
        GROUP BY t.position_code_2026_27,t.product_no
        ORDER BY t.position_code_2026_27,t.product_no''', args+ta) if available else []
    rows = {}
    for pos, product, group, target, units, tp, regular, additional in targets:
        rows[pos, product] = dict(position=pos, id=product, name=product or 'Unmapped product', group=group,
            target=target, unit_target=units, tp_target=tp, regular_budget=regular, additional_budget=additional,
            actual=0, units=0, positive=0, returns=0, tp=0, discounts=0)
    for pos, product, name, group, actual, units, tp, discounts, returns, positive, nvalue, nunits, bonus_discount in sales:
        row = rows.setdefault((pos,product), dict(position=pos,id=product))
        row.update(name=name or product or 'Unmapped product',group=group,actual=actual,units=units,tp=tp,
                   discounts=discounts,returns=returns,positive=positive, sales_count=nvalue, units_count=nunits, bonus_discount=bonus_discount)
    for row in rows.values():
        for key, value in list(row.items()):
            if value is not None and key not in {'position','id','name','group'}: row[key]=float(value)
    staff = query(f'''{cte} SELECT DISTINCT m.position_code,m.employee_name,m.designation_name,m.report_to_position_code
        FROM staff_master m WHERE m.position_code IN (SELECT position_code FROM scope)''', args)
    customers = query(f'''{cte} SELECT s.cust_number,MAX(s.cust_name), {positive_expr},
        {returns_expr}
        FROM {customer_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.cust_number''', args+[month,filters['fy']]+sa)
    if use_summaries:
        employee_kpis = query(f'''{cte}, actual AS (
            SELECT s.position_code,SUM(s.net_sale_value) actual,SUM(s.discounts) discount,
                   SUM(s.gross_tp_value) tp
            FROM {position_product_source} s
            WHERE s.position_code IN (SELECT position_code FROM scope)
              AND s.reporting_month=%s AND s.fiscal_year=%s {sw}
            GROUP BY s.position_code), customers AS (
            SELECT s.position_code,COUNT(DISTINCT NULLIF(s.cust_number,'')) ucc
            FROM {customer_source} s
            WHERE s.position_code IN (SELECT position_code FROM scope)
              AND s.reporting_month=%s AND s.fiscal_year=%s {sw}
            GROUP BY s.position_code)
            SELECT a.position_code,COALESCE(c.ucc,0),a.actual,a.discount,a.tp
            FROM actual a LEFT JOIN customers c USING(position_code)''',
            args+[month,filters['fy']]+sa+[month,filters['fy']]+sa)
        product_kpis = query(f'''{cte}, actual AS (
            SELECT s.product_no,SUM(s.net_sale_value) actual,SUM(s.discounts) discount,
                   SUM(s.gross_tp_value) tp
            FROM {position_product_source} s
            WHERE s.position_code IN (SELECT position_code FROM scope)
              AND s.reporting_month=%s AND s.fiscal_year=%s {sw}
            GROUP BY s.product_no), customers AS (
            SELECT s.product_no,COUNT(DISTINCT NULLIF(s.cust_number,'')) ucc
            FROM {customer_source} s
            WHERE s.position_code IN (SELECT position_code FROM scope)
              AND s.reporting_month=%s AND s.fiscal_year=%s {sw}
            GROUP BY s.product_no)
            SELECT a.product_no,COALESCE(c.ucc,0),a.actual,a.discount,a.tp
            FROM actual a LEFT JOIN customers c USING(product_no)''',
            args+[month,filters['fy']]+sa+[month,filters['fy']]+sa)
    else:
        employee_kpis = query(f'''{cte} SELECT s.position_code,COUNT(DISTINCT NULLIF(s.cust_number,'')),
            SUM(s.net_sale_value),SUM(s.discounts),SUM(s.tp_sale_value)
            FROM sales_data s WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.position_code''', args+[month,filters['fy']]+sa)
        product_kpis = query(f'''{cte} SELECT s.product_no,COUNT(DISTINCT NULLIF(s.cust_number,'')),
            SUM(s.net_sale_value),SUM(s.discounts),SUM(s.tp_sale_value)
            FROM sales_data s WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.product_no''', args+[month,filters['fy']]+sa)
    # Exact consecutive, completed reporting months; no missing month is filled with zero.
    end = date
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).date()
    if (date.year,date.month) >= (today.year,today.month): end = date.replace(day=1)-dt.timedelta(days=1)
    months=[]
    for _ in range(4):
        months.insert(0,end.strftime('%B,%y')); end=end.replace(day=1)-dt.timedelta(days=1)
    history = query(f'''{cte} SELECT s.reporting_month,SUM(s.net_sale_value) FROM {position_product_source} s
        WHERE s.position_code IN (SELECT position_code FROM scope) AND s.reporting_month=ANY(%s) {sw}
        GROUP BY s.reporting_month''', args+[months]+sa)
    hm = {m:float(v) for m,v in history if v is not None}
    prior_month = (date.replace(day=1) - dt.timedelta(days=1)).strftime('%B,%y')
    employee_prior = query(f'''{cte} SELECT s.position_code,SUM(s.net_sale_value)
        FROM {position_product_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.position_code''', args+[prior_month,filters['fy']]+sa)
    product_prior = query(f'''{cte} SELECT s.product_no,SUM(s.net_sale_value)
        FROM {position_product_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.product_no''', args+[prior_month,filters['fy']]+sa)
    # Root-cause evidence for the per-employee diagnosis. These are optional: a failure
    # must never take the whole insights endpoint down, so each degrades to empty.
    def optional(sql, params):
        try:
            return query(sql, params)
        except Exception:
            return []
    pos_customers = optional(f'''{cte} SELECT s.position_code,s.cust_number,MAX(s.cust_name),s.reporting_month,SUM(s.net_sale_value)
        FROM {customer_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=ANY(%s) AND COALESCE(s.cust_number,'')<>'' {sw}
        GROUP BY s.position_code,s.cust_number,s.reporting_month''', args+[[month, prior_month]]+sa)
    product_customers = optional(f'''{cte} SELECT s.product_no,s.cust_number,MAX(s.cust_name),s.reporting_month,SUM(s.net_sale_value)
        FROM {customer_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=ANY(%s) AND COALESCE(s.cust_number,'')<>'' {sw}
        GROUP BY s.product_no,s.cust_number,s.reporting_month''', args+[[month, prior_month]]+sa)
    pos_product_prior = optional(f'''{cte} SELECT s.position_code,s.product_no,SUM(s.net_sale_value)
        FROM {position_product_source} s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s {sw} GROUP BY s.position_code,s.product_no
        ORDER BY s.position_code,s.product_no''', args+[prior_month]+sa)
    pos_depot = optional(f'''{cte} SELECT s.position_code,s.depot_name,SUM(ABS(s.net_sale_value))
        FROM sales_data s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.position_code,s.depot_name''', args+[month,filters['fy']]+sa)
    product_depot = optional(f'''{cte} SELECT s.product_no,s.depot_name,SUM(ABS(s.net_sale_value))
        FROM sales_data s WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY s.product_no,s.depot_name''', args+[month,filters['fy']]+sa)
    # Inventory data is intentionally excluded: cpd_phr_daily_stock_ledger is
    # incomplete (only one day of data) and must not influence API results or
    # AI diagnoses.
    depot_stock = []
    missing_names = sorted({row['id'] for row in rows.values()
                            if row.get('id') and (not row.get('name') or row['name'] == row['id'])})
    product_names = dict(optional(f'''SELECT product_no,MAX(prd_name) FROM {position_product_source}
        WHERE reporting_month=ANY(%s) AND product_no=ANY(%s) GROUP BY product_no''',
        [[month, prior_month], missing_names])) if missing_names else {}
    for row in rows.values():
        if row.get('id') and (not row.get('name') or row['name'] == row['id']) and product_names.get(row['id']):
            row['name'] = product_names[row['id']]
    # Inventory belongs to depots, not employees. Only use depot/product pairs observed in this scope.
    # Keep the context contract stable for downstream analysis, but do not
    # query the incomplete inventory table.
    stock = []
    # An individual may be compared with the immediate reporting team's gross gap.
    parent_gap = None
    if filters['designation'] in {'MIO','SPO'} and filters['employee'] != 'All' and available:
        parents = {r[3] for r in staff if r[1] == filters['employee'] and r[3]}
        if len(parents) == 1:
            parent = next(iter(parents))
            if reporting_tree_resolver is None:
                parent_cte = """WITH RECURSIVE scope AS (SELECT position_code FROM staff_master WHERE position_code=%s
                    UNION SELECT m.position_code FROM staff_master m JOIN scope p ON m.report_to_position_code=p.position_code)"""
                parent_args = [parent]
            else:
                parent_positions = reporting_tree_resolver(parent)
                parent_cte = """WITH scope(position_code) AS (
                    SELECT DISTINCT position_code
                    FROM unnest(%s::text[]) AS resolved(position_code))"""
                parent_args = [parent_positions]
            team_rows = query(f"""{parent_cte}, t AS (
                SELECT t.position_code_2026_27 pos,SUM(t.tgt_net_w_reg_{sfx}) target FROM target_data t
                WHERE t.position_code_2026_27 IN (SELECT position_code FROM scope) {tw} GROUP BY 1), s AS (
                SELECT s.position_code pos,SUM(s.net_sale_value) actual FROM {position_product_source} s
                WHERE s.position_code IN (SELECT position_code FROM scope) AND s.reporting_month=%s AND s.fiscal_year=%s {sw} GROUP BY 1)
                SELECT SUM(GREATEST(t.target-COALESCE(s.actual,0),0)) FROM t LEFT JOIN s USING(pos)""",
                parent_args+ta+[month,filters['fy']]+sa)
            parent_gap = float(team_rows[0][0] or 0)
    # National mapping exceptions lie outside the normal staff hierarchy scope.
    # Never pull these into a selected employee or geography's performance.
    orphan_sales = orphan_targets = 0
    if filters['designation'] in {'ALL','HOD'} and all(filters[k]=='All' for k in ('employee','region','zone','subzone','territory')):
        orphan_abs = ('COALESCE(s.positive_net_sale_value,0) + COALESCE(s.negative_net_sale_abs,0)'
                      if use_summaries else 'ABS(s.net_sale_value)')
        orphan_sales = float(query(f"""SELECT SUM({orphan_abs}) FROM {position_product_source} s
            WHERE s.reporting_month=%s AND s.fiscal_year=%s {sw}
            AND NOT EXISTS(SELECT 1 FROM staff_master m WHERE m.position_code=s.position_code)""",
            [month,filters['fy']]+sa)[0][0] or 0)
        if available:
            orphan_targets = float(query(f"""SELECT SUM(t.tgt_net_w_reg_{sfx}) FROM target_data t
                WHERE NOT EXISTS(SELECT 1 FROM staff_master m WHERE m.position_code=t.position_code_2026_27) {tw}""",ta)[0][0] or 0)
    period_available = bool(query(
        f'SELECT 1 FROM {position_source} WHERE reporting_month=%s AND fiscal_year=%s LIMIT 1',
        [month,filters['fy']],
    ))
    return dict(parent_gap=parent_gap,orphan_sales=orphan_sales,orphan_targets=orphan_targets,period_available=period_available, rows=list(rows.values()),staff=staff,customers=customers,history=[(m,hm.get(m)) for m in months],
                employee_kpis={r[0]: dict(ucc=int(r[1] or 0), actual=float(r[2] or 0), discount=float(r[3] or 0), tp=float(r[4] or 0), previous=float(dict(employee_prior).get(r[0]) or 0)) for r in employee_kpis},
                product_kpis={r[0]: dict(ucc=int(r[1] or 0), actual=float(r[2] or 0), discount=float(r[3] or 0), tp=float(r[4] or 0), previous=float(dict(product_prior).get(r[0]) or 0)) for r in product_kpis},
                stock=stock,filters=filters,targets_available=available,
                pos_customers=pos_customers,product_customers=product_customers,pos_product_prior=pos_product_prior,pos_depot=pos_depot,product_depot=product_depot,
                depot_stock=depot_stock,product_names=product_names,prior_month=prior_month,
                partial_period=(date.year,date.month)>=(today.year,today.month))
