"""Per-employee root-cause diagnosis.

Turns raw evidence (product x position sales/targets, customer-level current vs
prior month, depot stock, discount budgets, returns and peer medians) into
*reasons*: why an employee is not selling, or why an employee is outperforming.

Everything is deterministic and evidence-backed; a finding is only emitted when
the data supports it, and every finding carries the numbers behind it.
"""
from collections import defaultdict
from statistics import median


def money(n):
    n = float(n or 0)
    return 'PKR ' + (f'{n/1e6:,.2f}M' if abs(n) >= 1e6 else f'{n/1e3:,.1f}K' if abs(n) >= 1000 else f'{n:,.0f}')


def _names(items, key='name', limit=3, extra=None):
    out = []
    for item in items[:limit]:
        label = item.get(key) or item.get('id') or 'Unmapped'
        out.append(f'{label} ({extra(item)})' if extra else str(label))
    return ', '.join(out)


def named_items(items, key='name', extra=None):
    """Return the full, display-ready evidence list for expandable findings."""
    return [
        dict(name=str(item.get(key) or item.get('id') or 'Unmapped'),
             value=str(extra(item)) if extra else '')
        for item in items
    ]


def build_index(context):
    """Group the flat context once so each employee diagnosis is O(own rows)."""
    rows = defaultdict(list)
    for row in context.get('rows', []):
        rows[row.get('position')].append(row)
    prior_month = context.get('prior_month')
    customers = defaultdict(dict)
    for pos, cust, name, month, value in context.get('pos_customers', []):
        entry = customers[pos].setdefault(cust, dict(name=name, cur=0.0, prior=0.0))
        entry['name'] = entry['name'] or name
        entry['prior' if month == prior_month else 'cur'] += float(value or 0)
    depots = defaultdict(dict)
    for pos, depot, value in context.get('pos_depot', []):
        depots[pos][depot] = depots[pos].get(depot, 0.0) + float(value or 0)
    stock = {}
    for product, depot, closing, avg, days in context.get('depot_stock', []):
        stock[depot, product] = (float(closing or 0), float(avg or 0), float(days) if days is not None else None)
    return dict(rows=rows, customers=customers, depots=depots, stock=stock)


def sold_products(positions, index):
    sold = set()
    for pos in positions:
        for row in index['rows'].get(pos, []):
            if (row.get('actual') or 0) > 0:
                sold.add(row.get('id'))
    return len(sold)


def benchmarks(cards, positions_of, index):
    """Peer medians across the cards being compared (None when too few peers)."""
    usable = [c for c in cards if (c.get('total_ucc') or 0) > 0 and (c.get('actual') or 0) > 0]
    if len(usable) < 5:
        return {}
    return dict(
        ucc=median(c['total_ucc'] for c in usable),
        spu=median(c['actual'] / c['total_ucc'] for c in usable),
        sold=median(sold_products(positions_of(c['employee_id']), index) for c in usable),
        peers=len(usable),
    )


def diagnose(positions, index, bench, card):
    actual = float(card.get('actual') or 0)
    target = float(card.get('target') or 0)
    ach = float(card.get('achievement_pct') or 0)
    ucc = int(card.get('total_ucc') or 0)
    gap = max(0.0, target - actual)
    material = max(1000.0, target * .03)

    # ---- product evidence -------------------------------------------------
    agg = defaultdict(lambda: defaultdict(float))
    names = {}
    tp = disc = budget = tp_target = 0.0
    for pos in positions:
        for row in index['rows'].get(pos, []):
            pid = row.get('id')
            a = agg[pid]
            for key in ('actual', 'target', 'units', 'unit_target', 'returns', 'positive'):
                a[key] += float(row.get(key) or 0)
            if row.get('name') and row['name'] != pid:
                names[pid] = row['name']
            tp += float(row.get('tp') or 0)
            disc += abs(float(row.get('discounts') or 0))
            budget += float(row.get('regular_budget') or 0) + float(row.get('additional_budget') or 0)
            tp_target += float(row.get('tp_target') or 0)
    products = []
    for pid, a in agg.items():
        products.append(dict(id=pid, name=names.get(pid) or pid or 'Unmapped product', actual=a['actual'], target=a['target'],
                             gap=max(0.0, a['target'] - a['actual']),
                             ach=(a['actual'] / a['target'] * 100) if a['target'] > 0 else None))
    with_target = [p for p in products if p['target'] > 0]
    sold = [p for p in products if p['actual'] > 0]
    returns = sum(a['returns'] for a in agg.values())
    positive = sum(a['positive'] for a in agg.values())
    units = sum(a['units'] for a in agg.values())
    unit_target = sum(a['unit_target'] for a in agg.values())
    uach = units / unit_target * 100 if unit_target > 0 else None
    disc_pct = disc / tp * 100 if tp > 0 else None
    budget_pct = budget / tp_target * 100 if tp_target > 0 else None
    disc_var = disc_pct - budget_pct if disc_pct is not None and budget_pct is not None else None

    # ---- customer evidence (current vs prior month) -----------------------
    cust = {}
    for pos in positions:
        for cid, v in index['customers'].get(pos, {}).items():
            m = cust.setdefault(cid, dict(name=v['name'] or cid, cur=0.0, prior=0.0))
            m['cur'] += v['cur']; m['prior'] += v['prior']
    buyers = [c for c in cust.values() if c['cur'] > 0]
    prior_buyers = [c for c in cust.values() if c['prior'] > 0]
    prior_total = sum(c['prior'] for c in prior_buyers)
    cur_total = sum(c['cur'] for c in buyers)
    has_prior = prior_total > 0
    lost = sorted([c for c in prior_buyers if c['cur'] <= 0], key=lambda c: -c['prior'])
    new = sorted([c for c in buyers if c['prior'] <= 0], key=lambda c: -c['cur'])
    kept = [c for c in buyers if c['prior'] > 0]
    reduced = sorted([c for c in kept if c['cur'] < c['prior']], key=lambda c: c['cur'] - c['prior'])
    grew = [c for c in kept if c['cur'] > c['prior']]
    lost_value = sum(c['prior'] for c in lost)
    new_value = sum(c['cur'] for c in new)
    reduced_value = sum(c['prior'] - c['cur'] for c in reduced)
    grew_value = sum(c['cur'] - c['prior'] for c in grew)
    decline = max(0.0, prior_total - cur_total)
    top3_share = (sum(sorted((c['cur'] for c in buyers), reverse=True)[:3]) / cur_total * 100) if cur_total > 0 and len(buyers) >= 4 else None

    # ---- depot stock evidence for the biggest gap products ---------------
    depot_sales = defaultdict(float)
    for pos in positions:
        for depot, value in index['depots'].get(pos, {}).items():
            depot_sales[depot] += value
    main_depot = max(depot_sales, key=depot_sales.get) if depot_sales else None
    stocked_out, stock_checked = [], 0
    if main_depot and index['stock']:
        for p in sorted(products, key=lambda p: -p['gap'])[:6]:
            if p['gap'] < material * .3:
                continue
            info = index['stock'].get((main_depot, p['id']))
            if not info:
                continue
            stock_checked += 1
            closing, avg, days = info
            if closing <= 0 or (days is not None and 0 <= days < 12 and avg > 0):
                stocked_out.append(dict(p, days=days, closing=closing))

    spu = actual / ucc if ucc > 0 else 0

    def item(title, detail, impact, evidence=(), related_items=()):
        related_items = list(related_items)
        return dict(title=title, detail=detail, impact=round(float(impact), 2), impact_label=money(impact),
                    evidence=[f'{k}: {v}' for k, v in evidence],
                    related_items=related_items[:20], related_total=len(related_items))

    cap = (lambda v: min(v, gap)) if gap > 0 else (lambda v: v)

    # ===================== WHY IT IS NOT SELLING ==========================
    blockers = []
    unsold = sorted([p for p in with_target if p['actual'] <= 0 and p['target'] >= max(500.0, target * .02)], key=lambda p: -p['target'])
    if unsold:
        value = sum(p['target'] for p in unsold)
        blockers.append(item('Targeted products not sold at all',
            f'{len(unsold)} of {len(with_target)} targeted products have zero sales this month: {_names(unsold, extra=lambda p: money(p["target"]))}. '
            f'Their target of {money(value)} is {cap(value)/gap*100:.0f}% of the shortfall.' if gap > 0 else
            f'{len(unsold)} targeted products have zero sales this month.',
            cap(value), [('Unsold products', f'{len(unsold)}/{len(with_target)}'), ('Target on them', money(value))],
            named_items(unsold, extra=lambda p: money(p['target']))))
    weak = sorted([p for p in with_target if p['actual'] > 0 and p['ach'] < 70 and p['gap'] >= material], key=lambda p: -p['gap'])
    if weak:
        value = sum(p['gap'] for p in weak)
        weak_label = lambda p: '%.0f%% of target' % p['ach']
        blockers.append(item('Products selling far below plan',
            f'{_names(weak, extra=weak_label)} are moving but well short, leaving {money(value)} uncollected.',
            cap(value), [('Products below 70%', len(weak)), ('Combined gap', money(value))],
            named_items(weak, extra=weak_label)))
    if has_prior and lost and lost_value >= material:
        share = f' This alone explains {min(100, lost_value / decline * 100):.0f}% of the drop versus last month.' if decline > 0 else ''
        blockers.append(item('Customers stopped ordering',
            f'{len(lost)} customers who bought {money(lost_value)} last month placed no order this month (largest: {_names(lost, extra=lambda c: money(c["prior"]))}).{share}',
            cap(lost_value), [('Lost customers', len(lost)), ('Lost sales', money(lost_value))],
            named_items(lost, extra=lambda c: money(c['prior']))))
    if has_prior and reduced and reduced_value >= material and reduced_value >= lost_value * .5:
        blockers.append(item('Existing customers are ordering less',
            f'{len(reduced)} retained customers cut their orders by {money(reduced_value)} versus last month (biggest drops: {_names(reduced, extra=lambda c: "-" + money(c["prior"] - c["cur"]))}).',
            cap(reduced_value), [('Customers buying less', len(reduced)), ('Reduction', money(reduced_value))],
            named_items(reduced, extra=lambda c: '-' + money(c['prior'] - c['cur']))))
    if bench.get('ucc') and ucc < bench['ucc'] * .65:
        missing = bench['ucc'] * .8 - ucc
        blockers.append(item('Thin customer coverage',
            f'Only {ucc} customers served versus a peer median of {bench["ucc"]:.0f}. Reaching 80% of the peer median would add about {missing:.0f} outlets.',
            cap(max(0, missing) * bench.get('spu', 0)), [('Customers', ucc), ('Peer median', f'{bench["ucc"]:.0f}')]))
    elif bench.get('spu') and ucc > 0 and spu < bench['spu'] * .7:
        blockers.append(item('Small orders per customer',
            f'Average sales per customer are {money(spu)} versus a peer median of {money(bench["spu"])}. Coverage is adequate, so the weakness is order size and range per call.',
            cap(max(0, bench['spu'] * .8 - spu) * ucc), [('Sales per customer', money(spu)), ('Peer median', money(bench['spu']))]))
    if stocked_out:
        value = sum(p['gap'] for p in stocked_out)
        stock_label = lambda p: 'no stock' if p['closing'] <= 0 else '%.0f days cover' % p['days']
        blockers.append(item('Stock shortage at the supplying depot',
            f'Depot {main_depot} is out of or very low on {_names(stocked_out, extra=stock_label)}, '
            f'so orders on {money(value)} of the gap cannot be fulfilled. Depot stock is shared, not employee-owned.',
            cap(value), [('Depot', main_depot), ('Gap products affected', len(stocked_out))],
            named_items(stocked_out, extra=stock_label)))
    if positive > 0 and returns >= material and returns / positive >= .03:
        blockers.append(item('Returns eroding net sales',
            f'Returns and reversals total {money(returns)} ({returns / positive * 100:.1f}% of gross sales) and are dragging net sales below target.',
            cap(returns), [('Returns', money(returns)), ('Return rate', f'{returns / positive * 100:.1f}%')]))
    if disc_var is not None and disc_var > 2 and tp > 0:
        leak = disc_var / 100 * tp
        blockers.append(item('Discount is not converting to sales',
            f'Discount is {disc_pct:.1f}% against a {budget_pct:.1f}% budget (+{disc_var:.1f} pp, about {money(leak)} extra) yet achievement is only {ach:.0f}%. '
            f'Discount-led orders are not producing volume.', leak, [('Actual discount', f'{disc_pct:.1f}%'), ('Budget', f'{budget_pct:.1f}%')]))
    if uach is not None and ach - uach >= 8:
        blockers.append(item('Volume lagging value',
            f'Units are at {uach:.0f}% of target versus {ach:.0f}% in value: fewer units are being sold, with price/mix masking the volume gap.',
            gap * .15, [('Unit achievement', f'{uach:.0f}%'), ('Value achievement', f'{ach:.0f}%')]))
    blockers.sort(key=lambda b: -b['impact'])
    blockers = blockers[:4]

    ruled_out = []
    if disc_var is not None and disc_var <= 2:
        ruled_out.append(f'Discount is not the cause: {disc_pct:.1f}% against a {budget_pct:.1f}% budget.')
    if stock_checked and not stocked_out:
        ruled_out.append(f'Stock is not the cause: depot {main_depot} has cover on the main gap products.')
    if has_prior and prior_total > 0 and lost_value / prior_total < .1:
        ruled_out.append(f'Customer base is intact: only {lost_value / prior_total * 100:.0f}% of last month\'s buyers were lost.')
    if positive > 0 and returns / positive < .02:
        ruled_out.append(f'Returns are not the cause ({returns / positive * 100:.1f}% of gross sales).')
    if bench.get('ucc') and ucc >= bench['ucc'] * .8:
        ruled_out.append(f'Coverage is in line with peers ({ucc} vs median {bench["ucc"]:.0f}).')
    ruled_out = ruled_out[:4]

    # ===================== WHY IT IS PERFORMING ===========================
    strengths, watch = [], []
    over = max(0.0, actual - target)
    hit = sorted([p for p in with_target if p['ach'] >= 100], key=lambda p: -(p['actual'] - p['target']))
    surplus = sum(p['actual'] - p['target'] for p in hit)
    if with_target and hit and len(hit) / len(with_target) >= .5:
        strengths.append(item('Delivering across the product range',
            f'Target met on {len(hit)} of {len(with_target)} products ({len(hit) / len(with_target) * 100:.0f}%). Biggest contributors: '
            f'{_names(hit, extra=lambda p: "+" + money(p["actual"] - p["target"]))}.', surplus,
            [('Products at target', f'{len(hit)}/{len(with_target)}'), ('Surplus on winners', money(surplus))],
            named_items(hit, extra=lambda p: '+' + money(p['actual'] - p['target']))))
    elif hit and surplus > 0 and (hit[0]['actual'] - hit[0]['target']) / surplus >= .6 and len(hit) <= 2:
        watch.append(item('Over-achievement rests on one product',
            f'{hit[0]["name"]} supplies {(hit[0]["actual"] - hit[0]["target"]) / surplus * 100:.0f}% of the surplus; only {len(hit)} of {len(with_target)} products met target.',
            hit[0]['actual'] - hit[0]['target']))
    if has_prior and (new_value >= material or grew_value >= material):
        strengths.append(item('Growing the customer base and basket',
            f'{len(new)} new customers added {money(new_value)} and {len(grew)} retained customers increased orders by {money(grew_value)}; only {len(lost)} customers were lost ({money(lost_value)}).',
            new_value + grew_value, [('New customers', len(new)), ('Customers buying more', len(grew))]))
    if has_prior and prior_total > 0 and lost_value / prior_total <= .05 and len(prior_buyers) >= 5:
        strengths.append(item('Strong customer retention',
            f'{(1 - lost_value / prior_total) * 100:.0f}% of last month\'s buying value was retained; almost no accounts went quiet.',
            prior_total - lost_value, [('Retained value', money(prior_total - lost_value))]))
    if bench.get('ucc') and ucc >= bench['ucc'] * 1.25:
        strengths.append(item('Wider customer coverage than peers',
            f'Serves {ucc} customers versus a peer median of {bench["ucc"]:.0f} (+{(ucc / bench["ucc"] - 1) * 100:.0f}%), which gives more orders per month.',
            (ucc - bench['ucc']) * bench.get('spu', 0), [('Customers', ucc), ('Peer median', f'{bench["ucc"]:.0f}')]))
    if bench.get('spu') and spu >= bench['spu'] * 1.25:
        strengths.append(item('Larger orders per customer',
            f'Average sales per customer are {money(spu)} versus a peer median of {money(bench["spu"])} (+{(spu / bench["spu"] - 1) * 100:.0f}%): deeper baskets and better range selling.',
            (spu - bench['spu']) * ucc, [('Per customer', money(spu)), ('Peer median', money(bench['spu']))]))
    if bench.get('sold') and len(sold) >= bench['sold'] * 1.2:
        strengths.append(item('Broader range sold',
            f'Sells {len(sold)} products versus a peer median of {bench["sold"]:.0f}, so growth does not depend on a few SKUs.',
            over, [('Products sold', len(sold)), ('Peer median', f'{bench["sold"]:.0f}')]))
    if disc_var is not None and disc_var <= 0 and ach >= 100 and tp > 0:
        strengths.append(item('Growth without extra discount',
            f'Achievement is {ach:.0f}% with discount {abs(disc_var):.1f} pp under budget ({disc_pct:.1f}% vs {budget_pct:.1f}%): sales are not being bought with price.',
            abs(disc_var) / 100 * tp, [('Discount', f'{disc_pct:.1f}%'), ('Budget', f'{budget_pct:.1f}%')]))
    if uach is not None and uach >= 100:
        strengths.append(item('Volume-backed growth',
            f'Units are at {uach:.0f}% of target alongside {ach:.0f}% in value, so the result comes from real volume.', over,
            [('Unit achievement', f'{uach:.0f}%')]))
    if positive > 0 and returns / positive < .01:
        strengths.append(item('Clean orders',
            f'Returns are only {returns / positive * 100:.2f}% of gross sales, so orders convert to net revenue.', over,
            [('Return rate', f'{returns / positive * 100:.2f}%')]))
    if card.get('golm_pct') is not None and card['golm_pct'] >= 10:
        strengths.append(item('Sustained momentum',
            f'Sales are up {card["golm_pct"]:.0f}% on last month ({money(card.get("previous_sales"))} to {money(actual)}).', max(0, actual - float(card.get('previous_sales') or 0)),
            [('Growth vs last month', f'{card["golm_pct"]:+.1f}%')]))
    strengths.sort(key=lambda s: -s['impact'])
    strengths = strengths[:4]

    if top3_share is not None and top3_share >= 55:
        watch.append(item('Dependent on a few customers',
            f'Top 3 customers supply {top3_share:.0f}% of sales; losing one would hit the result.', cur_total * top3_share / 100))
    if disc_var is not None and disc_var > 2 and ach >= 100 and tp > 0:
        watch.append(item('Growth bought with discount',
            f'Discount is {disc_var:.1f} pp above budget ({disc_pct:.1f}% vs {budget_pct:.1f}%), about {money(disc_var / 100 * tp)} extra. Check it is sustainable.',
            disc_var / 100 * tp))
    if unsold and ach >= 100:
        watch.append(item('Some targeted products still unsold',
            f'{len(unsold)} targeted products have zero sales ({_names(unsold)}); upside remains.', sum(p['target'] for p in unsold),
            related_items=named_items(unsold)))
    if has_prior and lost_value >= material and ach >= 100:
        watch.append(item('Accounts went quiet',
            f'{len(lost)} customers worth {money(lost_value)} last month did not order this month.', lost_value))
    watch.sort(key=lambda w: -w['impact'])
    watch = watch[:2]

    # Reasons must match the band: blockers only below target, strengths/watch-outs only at or above it.
    if ach >= 100:
        blockers, ruled_out = [], []
    else:
        watch = []
        strengths = [] if ach < 70 else strengths[:2]

    # ---- headline ---------------------------------------------------------
    if ach >= 100:
        headline = f'Top driver: {strengths[0]["title"]}.' if strengths else 'Above target, but no single dominant driver stands out in the available data.'
    elif blockers:
        headline = f'Main reason: {blockers[0]["title"]}.'
    else:
        headline = 'No single dominant cause found; the shortfall is spread thinly across products and customers.'

    bridge = None
    if has_prior:
        bridge = dict(prior=round(prior_total, 2), lost=round(-lost_value, 2), reduced=round(-reduced_value, 2),
                      new=round(new_value, 2), grew=round(grew_value, 2), current=round(cur_total, 2))
    return dict(headline=headline, blockers=blockers, strengths=strengths, watch=watch, ruled_out=ruled_out, bridge=bridge)
