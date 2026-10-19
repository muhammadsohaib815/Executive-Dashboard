"""Evidence-backed reasons for each product card in the selected sales scope."""
from collections import defaultdict

from .diagnosis import money, _names, named_items


def build_product_index(context):
    rows = defaultdict(list)
    for row in context.get('rows', []):
        rows[row.get('id')].append(row)
    customers = defaultdict(dict)
    prior_month = context.get('prior_month')
    for product, customer, name, month, value in context.get('product_customers', []):
        entry = customers[product].setdefault(customer, dict(name=name or customer, cur=0.0, prior=0.0))
        entry['prior' if month == prior_month else 'cur'] += float(value or 0)
    depots = defaultdict(dict)
    for product, depot, value in context.get('product_depot', []):
        depots[product][depot] = depots[product].get(depot, 0.0) + float(value or 0)
    stock = {}
    for product, depot, closing, avg, days in context.get('depot_stock', []):
        stock[product, depot] = (float(closing or 0), float(avg or 0), float(days) if days is not None else None)
    positions = {row[0]: row[1] or row[0] for row in context.get('staff', [])}
    return dict(rows=rows, customers=customers, depots=depots, stock=stock, positions=positions)


def diagnose_product(card, index):
    product = card.get('product_id')
    rows = index['rows'].get(product, [])
    actual = float(card.get('actual') or 0)
    target = float(card.get('target') or 0)
    achievement = float(card.get('achievement_pct') or 0)
    gap = max(0.0, target - actual)
    material = max(1000.0, target * .03)

    def item(title, detail, impact, evidence=(), related_items=()):
        related_items = list(related_items)
        return dict(title=title, detail=detail, impact=round(float(impact), 2),
                    impact_label=money(impact), evidence=[f'{k}: {v}' for k, v in evidence],
                    related_items=related_items[:20], related_total=len(related_items))

    blockers, strengths, watch, ruled_out = [], [], [], []
    positions = []
    for row in rows:
        position = row.get('position')
        sold = float(row.get('actual') or 0)
        plan = float(row.get('target') or 0)
        positions.append(dict(id=position, name=index['positions'].get(position) or position or 'Unmapped position',
                              actual=sold, target=plan, gap=max(0.0, plan - sold),
                              surplus=max(0.0, sold - plan)))
    targeted = [p for p in positions if p['target'] > 0]
    unsold = sorted([p for p in targeted if p['actual'] <= 0 and p['target'] >= material], key=lambda p: -p['target'])
    weak = sorted([p for p in targeted if p['actual'] > 0 and p['actual'] / p['target'] < .7 and p['gap'] >= material], key=lambda p: -p['gap'])
    winners = sorted([p for p in targeted if p['actual'] >= p['target']], key=lambda p: -p['surplus'])
    if unsold and gap > 0:
        value = sum(p['target'] for p in unsold)
        blockers.append(item('Targeted territories have no orders',
            f'{len(unsold)} of {len(targeted)} targeted positions booked no sales for this product. '
            f'Largest missing plans: {_names(unsold, extra=lambda p: money(p["target"]))}.',
            min(gap, value), [('Unsold positions', f'{len(unsold)}/{len(targeted)}')],
            named_items(unsold, extra=lambda p: money(p['target']))))
    if weak and gap > 0:
        value = sum(p['gap'] for p in weak)
        blockers.append(item('Product is moving slowly in key territories',
            f'{len(weak)} targeted positions are below 70% of their product plan, leaving {money(value)} of gross territory gap. '
            f'Largest gaps: {_names(weak, extra=lambda p: money(p["gap"]))}.',
            min(gap, value), [('Positions below 70%', len(weak))],
            named_items(weak, extra=lambda p: money(p['gap']))))
    if winners and len(winners) >= max(2, len(targeted) / 2):
        strengths.append(item('Sales are spread across targeted territories',
            f'{len(winners)} of {len(targeted)} targeted positions met or exceeded this product plan; '
            f'the largest surpluses are {_names(winners, extra=lambda p: "+" + money(p["surplus"]))}.',
            sum(p['surplus'] for p in winners), [('Positions at target', f'{len(winners)}/{len(targeted)}')],
            named_items(winners, extra=lambda p: '+' + money(p['surplus']))))

    customers = list(index['customers'].get(product, {}).values())
    prior_buyers = [c for c in customers if c['prior'] > 0]
    current_buyers = [c for c in customers if c['cur'] > 0]
    prior_total = sum(c['prior'] for c in prior_buyers)
    lost = sorted([c for c in prior_buyers if c['cur'] <= 0], key=lambda c: -c['prior'])
    reduced = sorted([c for c in current_buyers if c['prior'] > 0 and c['cur'] < c['prior']], key=lambda c: c['cur'] - c['prior'])
    new = sorted([c for c in current_buyers if c['prior'] <= 0], key=lambda c: -c['cur'])
    grew = sorted([c for c in current_buyers if c['prior'] > 0 and c['cur'] > c['prior']], key=lambda c: c['prior'] - c['cur'])
    lost_value = sum(c['prior'] for c in lost)
    reduced_value = sum(c['prior'] - c['cur'] for c in reduced)
    new_value = sum(c['cur'] for c in new)
    grew_value = sum(c['cur'] - c['prior'] for c in grew)
    if prior_total > 0 and lost_value >= material and gap > 0:
        blockers.append(item('Customers stopped ordering this product',
            f'{len(lost)} previous buyers placed no order for this product this month. They bought {money(lost_value)} last month; '
            f'largest lost accounts: {_names(lost, extra=lambda c: money(c["prior"]))}.',
            min(gap, lost_value), [('Lost product buyers', len(lost))],
            named_items(lost, extra=lambda c: money(c['prior']))))
    if prior_total > 0 and reduced_value >= material and gap > 0:
        blockers.append(item('Repeat buyers ordered less of this product',
            f'{len(reduced)} retained buyers reduced product orders by {money(reduced_value)} versus last month. '
            f'Largest reductions: {_names(reduced, extra=lambda c: money(c["prior"] - c["cur"]))}.',
            min(gap, reduced_value), [('Buyers ordering less', len(reduced))],
            named_items(reduced, extra=lambda c: money(c['prior'] - c['cur']))))
    if prior_total > 0 and new_value >= material:
        strengths.append(item('New buyers are adding product sales',
            f'{len(new)} customers who did not buy this product last month ordered {money(new_value)} this month. '
            f'Largest new buyers: {_names(new, extra=lambda c: money(c["cur"]))}.',
            new_value, [('New product buyers', len(new))],
            named_items(new, extra=lambda c: money(c['cur']))))
    if prior_total > 0 and grew_value >= material:
        strengths.append(item('Repeat buyers are ordering more',
            f'{len(grew)} existing product buyers increased orders by {money(grew_value)} versus last month. '
            f'Largest increases: {_names(grew, extra=lambda c: money(c["cur"] - c["prior"]))}.',
            grew_value, [('Buyers ordering more', len(grew))],
            named_items(grew, extra=lambda c: money(c['cur'] - c['prior']))))
    if prior_total > 0 and lost_value / prior_total <= .05 and len(prior_buyers) >= 5:
        strengths.append(item('Product buyers are being retained',
            f'{(1 - lost_value / prior_total) * 100:.0f}% of last month\'s product buying value remains with active buyers.',
            prior_total - lost_value))

    positive = sum(float(r.get('positive') or 0) for r in rows)
    returns = sum(float(r.get('returns') or 0) for r in rows)
    units = sum(float(r.get('units') or 0) for r in rows)
    unit_target = sum(float(r.get('unit_target') or 0) for r in rows)
    unit_achievement = units / unit_target * 100 if unit_target > 0 else None
    if positive > 0 and returns >= material and returns / positive >= .03 and gap > 0:
        blockers.append(item('Returns are reducing net product sales',
            f'{money(returns)} of returns or reversals equal {returns / positive * 100:.1f}% of positive product sales.',
            min(gap, returns), [('Return rate', f'{returns / positive * 100:.1f}%')]))
    elif positive > 0 and returns / positive < .01:
        strengths.append(item('Product orders have few returns',
            f'Returns are {returns / positive * 100:.2f}% of positive product sales, so most booked value remains in net sales.',
            max(0.0, actual - target)))
    if unit_achievement is not None and achievement - unit_achievement >= 8 and gap > 0:
        blockers.append(item('Unit movement trails sales value',
            f'Product units reached {unit_achievement:.0f}% of plan versus {achievement:.0f}% in value; physical movement is weaker than the revenue result.',
            gap * .15, [('Unit achievement', f'{unit_achievement:.0f}%')]))
    if unit_achievement is not None and unit_achievement >= 100 and achievement >= 100:
        strengths.append(item('Product growth is backed by units',
            f'Units reached {unit_achievement:.0f}% of plan alongside {achievement:.0f}% in sales value.',
            max(0.0, actual - target)))

    discount_variance = card.get('discount_variance_pp')
    if discount_variance is not None:
        discount_variance = float(discount_variance)
        if discount_variance > 2 and gap > 0:
            blockers.append(item('Extra discount has not closed the gap',
                f'Product discount is {card["discount_pct"]:.1f}% against a {card["discount_budget_pct"]:.1f}% budget '
                f'(+{discount_variance:.1f} pp), yet sales remain {money(gap)} below plan.',
                gap * .1, [('Discount over budget', f'{discount_variance:.1f} pp')]))
        elif discount_variance <= 0 and achievement >= 100:
            strengths.append(item('Target met within discount budget',
                f'This product reached {achievement:.1f}% of plan with discount {card["discount_pct"]:.1f}% '
                f'against a {card["discount_budget_pct"]:.1f}% budget.',
                max(0.0, actual - target)))
        if discount_variance <= 2 and gap > 0:
            ruled_out.append(f'Excess discount is not evident: {card["discount_pct"]:.1f}% actual versus {card["discount_budget_pct"]:.1f}% budget.')

    depot_sales = index['depots'].get(product, {})
    for depot, _ in sorted(depot_sales.items(), key=lambda pair: -pair[1])[:3]:
        stock = index['stock'].get((product, depot))
        if not stock:
            continue
        closing, avg, days = stock
        if closing < 0 or (days is not None and days < 0):
            continue
        if gap > 0 and (closing == 0 or (avg > 0 and days is not None and days < 12)):
            cover = 'no closing stock' if closing == 0 else f'{days:.0f} days of cover'
            blockers.append(item('Low shared depot stock may limit orders',
                f'Depot {depot} has {cover} for this product in the selected month. Confirm allocation and demand before attributing the sales gap to supply.',
                min(gap, depot_sales[depot]), [('Depot', depot), ('Stock cover', cover)]))
        elif gap > 0 and closing > 0 and days is not None and 15 <= days <= 45:
            ruled_out.append(f'Depot {depot} has {days:.0f} days of shared stock cover; availability there does not explain the gap.')

    if prior_total > 0 and lost_value / prior_total < .1 and gap > 0:
        ruled_out.append(f'Buyer loss is limited to {lost_value / prior_total * 100:.0f}% of last month\'s product buying value.')
    if positive > 0 and returns / positive < .02 and gap > 0:
        ruled_out.append(f'Returns are only {returns / positive * 100:.1f}% of positive product sales.')
    if achievement >= 100:
        if lost_value >= material:
            watch.append(item('Some product buyers went quiet',
                f'{len(lost)} customers who bought {money(lost_value)} of this product last month placed no order this month.', lost_value))
        if discount_variance is not None and discount_variance > 2:
            watch.append(item('Product growth used extra discount',
                f'Discount is {discount_variance:.1f} pp above budget while the product is above target.',
                max(0.0, actual - target)))
        if len(winners) == 1 and len(targeted) >= 3 and winners[0]['surplus'] > 0:
            watch.append(item('One territory carries the product surplus',
                f'{winners[0]["name"]} is the only targeted position above plan, contributing {money(winners[0]["surplus"])} of surplus.',
                winners[0]['surplus']))

    blockers.sort(key=lambda finding: -finding['impact'])
    strengths.sort(key=lambda finding: -finding['impact'])
    watch.sort(key=lambda finding: -finding['impact'])
    if achievement >= 100:
        blockers, ruled_out = [], []
        headline = f'Top driver: {strengths[0]["title"]}.' if strengths else 'Above target; the available evidence does not isolate one dominant driver.'
    else:
        strengths = strengths[:2] if achievement >= 70 else []
        watch = []
        headline = f'Main reason: {blockers[0]["title"]}.' if blockers else 'Below target; the available evidence does not isolate one dominant cause.'
    bridge = None
    if prior_total > 0:
        bridge = dict(prior=round(prior_total, 2), lost=round(-lost_value, 2),
                      reduced=round(-reduced_value, 2), new=round(new_value, 2),
                      grew=round(grew_value, 2), current=round(sum(c['cur'] for c in current_buyers), 2))
    return dict(headline=headline, blockers=blockers[:4], strengths=strengths[:4],
                watch=watch[:2], ruled_out=ruled_out[:4], bridge=bridge)
