# AI Sales Insights Catalog (Good and Bad Insights)

Comprehensive reference guide of all deterministic insights, root-cause diagnoses, strengths, and risks implemented in the Executive Dashboard AI Analysis engine.

---

## Part 1: Individual Employee & Team Deep-Dive Insights (`scripts/services/ai_analysis/diagnosis.py`)

These insights appear on each individual employee and manager card to explain *why* an employee is underperforming or outperforming, replacing basic restatements with underlying root causes.

### 🔴 BAD / REASONS FOR UNDERPERFORMANCE (Blockers & Root Causes)

| Insight Title | Category | Trigger / Condition | Business Meaning & Evidence |
| :--- | :--- | :--- | :--- |
| **Targeted products not sold at all** | Product Mix | Employee has targeted SKUs with PKR 0 sales this month. | Target was assigned on key products, but the rep did not book a single order. Quantifies the missing target value and product names. |
| **Products selling far below plan** | Execution | Targeted products have sales, but achievement < 70% with material gap. | The rep is moving products, but volume is far below quota. Highlights the lagging products and uncollected gap. |
| **Customers stopped ordering** | Churn / Retention | Customers who purchased last month placed zero orders this month. | Quantifies lost revenue, lists top churned accounts, and calculates the percentage of the monthly decline caused by customer loss. |
| **Existing customers ordering less** | Basket Contraction | Retained customers significantly reduced order sizes vs. last month. | Wallet-share erosion across recurring accounts. Shows top accounts with reduced spending. |
| **Thin customer coverage** | Territory Coverage | Active customer count (UCC) < 65% of peer median. | Under-visiting outlets; customer coverage is too narrow compared to peers. Computes how many outlets are needed to catch up. |
| **Small orders per customer** | Call Productivity | Sales per outlet (SPU) < 70% of peer median despite adequate coverage. | Adequate coverage, but orders per call are shallow (lack of cross-selling, poor basket size). |
| **Stock shortage at supplying depot** | Supply Chain / Inventory | Main supplying depot has 0 stock or < 12 days cover on gap products. | External constraint: orders could not be fulfilled due to depot stockout. (Note: depot stock is shared, not employee-owned). |
| **Returns eroding net sales** | Quality / Reversals | Returns/credit notes ≥ 3% of gross sales and ≥ material threshold. | Net achievement dragged down by rejected goods, near-expiry returns, or order cancellations. |
| **Discount is not converting to sales** | Margin / Pricing | Discount is > 2 pp above budget, yet achievement is < 70%. | Price discounting without volume payoff: excessive discounts given without achieving the quota. |
| **Volume lagging value** | Unit Delivery | Unit achievement trails value achievement by ≥ 8 percentage points. | Revenue is masked by price inflation/mix while physical box/unit movement is severely lagging behind. |

---

### 🟢 GOOD / REASONS FOR HIGH PERFORMANCE (Strengths & Drivers)

| Insight Title | Category | Trigger / Condition | Business Meaning & Evidence |
| :--- | :--- | :--- | :--- |
| **Delivering across the product range** | Product Breadth | ≥ 50% of targeted products achieved 100%+ of quota. | Balanced portfolio selling rather than relying on one or two high-demand SKUs. |
| **Growing customer base & basket** | Growth Engine | Material net gains from newly acquired customers and expanding repeat buyers. | Healthy commercial growth driven by both new account acquisition and wallet-share expansion. |
| **Strong customer retention** | Loyalty / Retention | ≥ 95% of last month’s customer revenue retained (loss ≤ 5%). | Near-zero churn; customer relationships and order replenishment are stable and recurring. |
| **Wider customer coverage than peers** | Active Coverage | Active outlets (UCC) ≥ 25% above peer median. | High field discipline and aggressive outlet opening/visitation compared to peers. |
| **Larger orders per customer** | Basket Size | Average sales per UCC (SPU) ≥ 25% above peer median. | Stronger cross-selling, bulk orders, and higher order values per call. |
| **Broader range sold** | SKU Penetration | Total distinct active SKUs sold ≥ 20% above peer median. | High range penetration across chemist/retail counters. |
| **Growth without extra discount** | Pricing Discipline | Achievement ≥ 100% while discount is within or below budget. | Profitable sales delivery without giving away company margin. |
| **Volume-backed growth** | Unit Performance | Unit achievement ≥ 100% alongside value achievement. | Real physical volume growth, not artificial nominal price gains. |
| **Clean orders** | Order Integrity | Returns/reversals < 1% of gross sales. | High order quality, correct fulfillment, and minimal returns. |
| **Sustained momentum** | Trend | Sales grew ≥ 10% vs. the previous month (positive GOLM). | Positive trajectory and expanding sales run-rate. |

---

### ⚠️ WATCH-OUTS FOR HIGH ACHIEVERS (Risks Hidden Behind High Numbers)

* **Dependent on a few customers:** Top 3 customers account for > 55% of revenue (vulnerable if any key account churns).
* **Growth bought with discount:** 100%+ sales achieved, but discount exceeded the allowed budget (margin sacrifice).
* **Over-achievement rests on one product:** A single SKU supplies > 60% of the entire surplus while other targeted SKUs lagged.
* **Some targeted products still unsold:** Target achieved overall, but certain strategic products had zero movement.
* **Accounts went quiet:** High total sales, but high-value accounts from last month placed zero orders.

---

### 🛡️ RULED-OUT EVIDENCE (Eliminating False Explanations)

* **Discount ruled out:** Discount is strictly within budget (sales drop is not caused by high prices or lack of discount).
* **Stock ruled out:** Supplying depot has sufficient inventory on key products (failure is in field execution/demand, not supply).
* **Customer base ruled out:** Customer retention rate was > 90% (accounts are active; order drop is from specific SKUs/quantities).
* **Returns ruled out:** Return rate was negligible (< 2%).
* **Coverage ruled out:** Outlet count is in line with or ahead of peers (coverage is adequate; problem is call productivity).

---

### 🌉 CUSTOMER BRIDGE METRIC

Every employee card includes a month-over-month customer bridge:
* **Prior Month Base Sales**
* **Lost Customers (Churned accounts)**: Negative impact
* **Buying Less (Contraction in repeat accounts)**: Negative impact
* **New Customers (Newly activated accounts)**: Positive impact
* **Buying More (Expansion in repeat accounts)**: Positive impact
* **Current Month Actual Sales**

---

## Part 2: Macro & Portfolio-Level Insights (`scripts/services/ai_analysis/engine.py` & `insight_ranker.py`)

These represent territory-wide, team-wide, and portfolio-wide findings ranked by normalized financial impact, severity, urgency, actionability, and confidence scores.

### 🔴 BAD / NEGATIVE MACRO FINDINGS

1. **Major Target Shortfall (`sales_target`)**
   * *Trigger:* Net sales achievement < 95% with shortfall exceeding 1% of total baseline.
   * *Meaning:* Core revenue gap. Identifies total PKR deficit, share of manager's gap, and the top 2 products driving the shortfall.

2. **Largest Product Gap (`product_gap`)**
   * *Trigger:* A single product represents ≥ 25% of the total gross product shortfall.
   * *Meaning:* Identifies high-leverage SKU where immediate recovery actions produce the largest return.

3. **Volume Behind Value (`unit_volume`)**
   * *Trigger:* Unit achievement < 85% and trails value achievement by ≥ 8 percentage points.
   * *Meaning:* Volume warning: physical box movement is falling behind financial value, indicating price/mix dependency.

4. **Discount Leakage (`discount_efficiency`)**
   * *Trigger:* Actual regular discount ≥ 1 pp above budget in an underperforming scope (achievement < 90%).
   * *Meaning:* High financial leakage: identifies the primary product responsible and calculates excess discount cost.

5. **Additional Discount Over Budget (`discount_efficiency`)**
   * *Trigger:* Bonus/additional discount exceeds additional discount budget by ≥ 1 pp.
   * *Meaning:* Promotional discount overspend without incremental volume justification.

6. **Declining Sales Momentum (`sales_momentum`)**
   * *Trigger:* Sales drop ≥ 10% month-over-month across at least 3 consecutive completed reporting months.
   * *Meaning:* Sustained negative trajectory; prompts investigation into lost orders and declining accounts.

7. **Return Impact (`return_impact`)**
   * *Trigger:* Return/reversal lines ≥ 2% of positive sales and ≥ material threshold.
   * *Meaning:* High cancellations, credit notes, or stock reversals. Isolates responsible customer accounts and products.

8. **Low Depot Stock / Stockout (`stock_risk`)**
   * *Trigger:* Critical SKU has < 12 days inventory coverage at a shared depot.
   * *Meaning:* Operational constraint: depot stockout risks unfulfilled orders.

9. **Dead Stock Exposure (`stock_risk`)**
   * *Trigger:* Significant inventory units at depot with zero recorded average sales.
   * *Meaning:* Working capital trapped in non-moving inventory; risks expiration.

10. **Excess Depot Stock (`stock_risk`)**
    * *Trigger:* Inventory days ≥ 90 days at depot.
    * *Meaning:* Overstocking beyond standard replenishment cycles.

11. **Concentrated Team Shortfall (`employee_underperformance`)**
    * *Trigger:* 1 to 3 reporting teams/subordinates account for the majority of a manager's deficit.
    * *Meaning:* Pinpoints specific subordinate teams requiring direct managerial intervention.

12. **Vacant Territory Exposure (`vacancy_coverage`)**
    * *Trigger:* Positions flagged as Vacant/Unmanned carrying active sales targets.
    * *Meaning:* Uncovered territory quota risk; highlights the need for temporary coverage.

13. **Customer Dependency (`customer_concentration`)**
    * *Trigger:* Top 3 customers account for ≥ 55% of positive sales.
    * *Meaning:* Revenue concentration risk; high vulnerability if key accounts switch suppliers.

14. **Unbalanced Product Portfolio (`product_mix`)**
    * *Trigger:* A single product group represents ≥ 65% of sales while ≥ 2 targeted SKUs achieve < 50%.
    * *Meaning:* Portfolio skew: sales force selling comfortable lines while ignoring strategic quota products.

15. **Data Quality Exceptions (`data_quality`)**
    * *Trigger:* Unmapped product IDs, invalid position codes, or unmatched national sales/targets.
    * *Meaning:* Reconciliation alert: prevents judging employees on incomplete master data mappings.

---

### 🟢 GOOD / POSITIVE MACRO FINDINGS

1. **Strong Growth Driver (`growth_driver`)**
   * *Trigger:* Product achieves ≥ 110% of quota and contributes substantial surplus over plan.
   * *Meaning:* Star performer SKU; recommends protecting order fulfillment and replicating sales patterns.

2. **Growing Sales Momentum (`sales_momentum`)**
   * *Trigger:* Consecutive completed months showing ≥ 10% month-over-month growth.
   * *Meaning:* Expansionary momentum; recommends protecting accounts driving growth.

3. **Efficient Sales Delivery (`discount_efficiency`)**
   * *Trigger:* Achievement ≥ 105% while regular discount remains strictly within budget.
   * *Meaning:* High-margin, profitable growth delivered with commercial pricing discipline.

4. **Stock-Supported Recovery (`recovery_opportunity`)**
   * *Trigger:* Underperforming products (gap ≥ threshold) have healthy depot coverage (15–45 days).
   * *Meaning:* Actionable opportunity: immediate target recovery is possible without supply chain delays.

5. **Unused Pricing Headroom (`discount_efficiency`)**
   * *Trigger:* Sales under plan (< 85%) while discount is ≥ 1 pp below budget.
   * *Meaning:* Available promotional headroom: management can offer budget-compliant incentives to stimulate volume.

---

## Part 3: Individual Product Card Diagnoses (`scripts/services/ai_analysis/product_diagnosis.py`)

The Product option keeps the same portfolio filters and cards. Each card uses the expandable diagnosis layout from Employee, with product-specific evidence from targeted positions, customer orders, returns, units, discount budgets, and matched shared depots. A customer bridge compares this product's buyers with the previous month when prior orders exist.

### Reasons a product is below target

| Insight | Trigger | Evidence shown |
| :--- | :--- | :--- |
| Targeted territories have no orders | A position with a material product target records zero product sales. | Number of unsold targeted positions and their missing plan. |
| Product is moving slowly in key territories | A targeted position sells the product but reaches under 70% of its product plan with a material gap. | Largest position gaps and combined gross gap. |
| Customers stopped ordering this product | Previous product buyers place no order in the current month. | Lost buyers, last month's product value, and largest accounts. |
| Repeat buyers ordered less of this product | Retained product buyers reduce their order value materially. | Number of buyers and value of the contraction. |
| Returns are reducing net product sales | Returns are at least 3% of positive product sales and material. | Return value and rate. |
| Unit movement trails sales value | Unit achievement trails value achievement by at least 8 percentage points. | Unit and value achievement. |
| Extra discount has not closed the gap | Discount exceeds budget by over 2 percentage points while the product is below target. | Actual and budget discount rates with the remaining sales gap. |
| Low shared depot stock may limit orders | A matched selling depot has zero stock or under 12 days of cover. | Depot and stock cover; the card asks for allocation and demand confirmation. |

### Reasons a product is selling well

| Insight | Trigger | Evidence shown |
| :--- | :--- | :--- |
| Sales are spread across targeted territories | At least half of targeted positions, and at least two positions, meet the product plan. | Positions at target and largest surpluses. |
| New buyers are adding product sales | Customers who did not buy this product last month add material current sales. | New buyers and their product order value. |
| Repeat buyers are ordering more | Existing product buyers expand orders materially. | Expanding buyers and value added. |
| Product buyers are being retained | At least 95% of prior product buying value remains active across five or more buyers. | Retained buying value. |
| Product orders have few returns | Returns are under 1% of positive product sales. | Return rate. |
| Product growth is backed by units | Product unit and value achievements both reach 100%. | Unit and value achievement. |
| Target met within discount budget | Product reaches target with discount at or below budget. | Actual and budget discount rates. |

### Product performance watch-outs

| Insight | Trigger | Evidence shown |
| :--- | :--- | :--- |
| One territory carries the product surplus | The product is above target, at least three positions have targets, and only one targeted position is above plan. | Leading position and its contribution to the product's surplus. |

Above-target cards can also flag lost buyers, excess discount, or surplus concentrated in one territory. Below-target cards rule out explanations only when the matching evidence is available. If no dominant driver is supported, the headline says so instead of inventing a cause.
