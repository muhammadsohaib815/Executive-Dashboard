/* ------------------------------------------------------------------
   Dashboard layout configuration – one entry per DESIGNATION.
   Structure only: no data values. Every block renders as a skeleton
   until real data is wired in later.

   panel.span  -> columns out of 12
   panel.blocks[] -> see components.js for supported block types
------------------------------------------------------------------- */

// API metadata replaces this list with every designation in staff_master.
// Keep the known roles here so the dashboard can render immediately.
const DESIGNATIONS = ["ALL", "SPO", "MIO", "ASM", "RSM", "HOD", "ASMTE", "CM", "DGM", "EXEC", "PS", "SB", "SPOWS", "TE"];

const MONTHS = [
  "Jul-2026", "Aug-2026", "Sep-2026", "Oct-2026", "Nov-2026", "Dec-2026",
  "Jan-2027", "Feb-2027", "Mar-2027", "Apr-2027", "May-2027", "Jun-2027"
];
const FISCAL_YEARS = ["2026-27", "2025-26"];

const DASHBOARDS = {
  /* ============================ HOD ============================ */
  "HOD": {
    key: "hod",
    title: "HOD / NATIONAL EXECUTIVE DASHBOARD",
    subtitle: "National Summary | Strategic View | Executive Monitoring",
    kpis: [
      { label: "GROSS TP ACH.", icon: "bars", tone: "green", sub: "Actual / Target" },
      { label: "NET SALES ACH.", icon: "coin", tone: "blue", sub: "Actual / Target" },
      { label: "UNITS ACH.", icon: "cube", tone: "cyan", sub: "Actual / Target" },
      { label: "DISCOUNT % VS BUDGET", icon: "percent", tone: "orange", sub: "Budget | variance" },
      { label: "CYP ACH.", icon: "lock", tone: "green", sub: "Actual / Target" }
    ],
    panels: [
      { n: 1, span: 4, title: "REGION RANKING — NET SALES ACHIEVEMENT", icon: "bars",
        fields: "REGION_NAME | NET_SALE_VALUE | TARGET_NET_SALE_VALUE",
        blocks: [{ type: "hbar", rows: 6 }] },
      { n: 2, span: 4, title: "NATIONAL VALUE PERFORMANCE — TARGET VS ACTUAL", icon: "bars",
        fields: "TP_SALE_VALUE | NET_SALE_VALUE | NET_WO_REG_DISC_VALUE | CYP | TARGETS",
        blocks: [{ type: "legend", items: ["Target", "Actual"] },
                 { type: "columns", groups: ["Gross TP", "Net Sales (W/Reg)", "Net WO/Reg", "CYP", "COGS"] }] },
      { n: 3, span: 4, title: "DISCOUNT, PROFITABILITY & EXCEPTIONS", icon: "percent", iconTone: "red",
        fields: "DISCOUNTS | TP_SALE_VALUE | NET_WO_REG_DISC_VALUE | CYP",
        blocks: [{ type: "split", left: { type: "donut", legend: ["Trade Discount", "Bonus Discount", "FOC Discount", "Other"], center: "Total Discount", title: "Discount Composition (Actual)" },
                                   right: [{ type: "budget" }, { type: "statCards", cols: 2, items: [{ label: "Gross Margin", icon: "coin", tone: "green" }, { label: "COGS", icon: "cube", tone: "blue" }] }] }] },

      { n: 4, span: 4, title: "GEOGRAPHIC PERFORMANCE", icon: "pin",
        fields: "PROVINCE | DISTRICT | NET_SALE_VALUE | TARGET | ACH. %",
        blocks: [{ type: "split", left: { type: "map" },
                                   right: [{ type: "table", cols: ["Province", "Net Sales (Rs.)", "Target (Rs.)", "Ach. %"], rows: 6 }] }] },
      { n: 5, span: 4, title: "CHANNEL / SHOP COVERAGE", icon: "shop",
        fields: "CHANNEL | CUST_NUMBER | INVOICE_NO | NET_SALE_VALUE",
        blocks: [{ type: "statCards", cols: 3, items: [{ label: "Active Shops", icon: "shop", tone: "green" }, { label: "Invoice Count", icon: "doc", tone: "blue" }, { label: "New Shops", icon: "plus", tone: "violet" }] },
                 { type: "legend", items: ["Target", "Actual"], title: "Sales by Channel (Actual vs Target)" },
                 { type: "columns", groups: ["Pharmacies", "General Trade", "Hospitals", "Others"], compact: true }] },
      { n: 6, span: 4, title: "TOP / BOTTOM PRODUCTS — NET SALES ACHIEVEMENT", icon: "cube",
        fields: "PRODUCT_NAME | NET_SALE_VALUE | TARGET | ACH. %",
        blocks: [{ type: "dual", left: { title: "Top 5 Products", tone: "green", rows: 5 }, right: { title: "Bottom 5 Products", tone: "red", rows: 5 } }] },

      { n: 7, span: 6, title: "MONTHLY TREND & DESIGNATION CONTRIBUTION", icon: "trend",
        fields: "REPORTING_MONTH | NET_SALE_VALUE | TARGET | DESIGNATION (HOD)",
        blocks: [{ type: "tabs", items: ["Monthly Trend", "Yearly Trend", "Designation Contribution"] },
                 { type: "legend", items: ["Actual", "Target", "Units (000s)"] },
                 { type: "line", months: true }] },
      { n: 8, span: 6, title: "NATIONAL INSIGHTS & STRATEGIC ACTION PLAN", icon: "bulb",
        blocks: [{ type: "split", left: { type: "insights", title: "Key Insights (National)", rows: 5 },
                                   right: [{ type: "actions", title: "Strategic Action Plan (HOD)", rows: 5 }] }] }
    ]
  },

  /* ============================ RSM ============================ */
  "RSM": {
    key: "rsm",
    title: "RSM REGIONAL PERFORMANCE DASHBOARD",
    subtitle: "Regional Oversight | ASM Performance | Target vs Actual",
    kpis: [
      { label: "GROSS TP ACH.", icon: "bars", tone: "green", sub: "Actual / Target" },
      { label: "NET SALES ACH.", icon: "rupee", tone: "blue", sub: "Actual / Target" },
      { label: "UNITS ACH.", icon: "cube", tone: "violet", sub: "Actual / Target" },
      { label: "DISCOUNT %", icon: "percent", tone: "orange", sub: "Budget | variance" },
      { label: "CYP ACH.", icon: "db", tone: "red", sub: "Actual / Target" }
    ],
    panels: [
      { n: 1, span: 4, title: "ASM / AREA RANKING", icon: "users",
        fields: "EMPLOYEE_NAME | NET_SALE_VALUE", desc: "Net Sales Achievement % by ASM (EMPLOYEE_NAME)",
        blocks: [{ type: "hbar", rows: 7 }] },
      { n: 2, span: 4, title: "REGIONAL VALUE PERFORMANCE — TARGET VS ACTUAL", icon: "bars",
        fields: "NET_SALE_VALUE | NET_WO_REG_DISC_VALUE | CYP", desc: "Target vs Actual (Values in Rs. Millions)",
        blocks: [{ type: "legend", items: ["Target", "Actual"] },
                 { type: "columns", groups: ["Gross TP", "Net Sales (W/Reg)", "Net WO/Reg", "CYP"], pills: true }] },
      { n: 3, span: 4, title: "DISCOUNT, PROFITABILITY & EXCEPTIONS", icon: "gear",
        blocks: [{ type: "split", left: { type: "budget" },
                                   right: [{ type: "donut", legend: ["Trade Discount", "Bonus Discount", "FOC Discount", "Other"], center: "Total Discount" }] },
                 { type: "statCards", cols: 3, items: [{ label: "Gross Margin", icon: "rupee", tone: "green" }, { label: "COGS", icon: "gear", tone: "blue" }, { label: "Exceptions", icon: "alert", tone: "red", wide: true }] }] },

      { n: 4, span: 4, title: "CATEGORY / PRODUCT PERFORMANCE", icon: "cube",
        fields: "PRODUCT_NO | PRD_NAME", desc: "Net Sales Achievement % by Product (PRODUCT_NO / PRD_NAME)",
        blocks: [{ type: "hbar", rows: 8, labelWide: true }] },
      { n: 5, span: 4, title: "REGION / SUB-ZONE SUMMARY", icon: "map",
        fields: "TEAM_REGION | REGION_NAME | ZONE | SUB_ZONE | NET_SALE_VALUE",
        blocks: [{ type: "table", cols: ["Region", "Zone", "Sub Zone", "Actual (Rs.)", "Target (Rs.)", "Ach. %"], rows: 8, total: true }] },
      { n: 6, span: 4, title: "TOP / BOTTOM CUSTOMERS OR DISTRICTS", icon: "users",
        fields: "CUST_NAME | NET_SALE_VALUE | NET_QTY",
        blocks: [{ type: "tabs", items: ["Top 5 Customers", "Bottom 5 Customers / Districts"], pill: true },
                 { type: "table", cols: ["#", "Customer / District", "Net Sales (Rs.)", "Units", "Ach. %"], rows: 5 }] },

      { n: 7, span: 4, title: "MONTHLY TREND", icon: "trend",
        fields: "REPORTING_MONTH | NET_SALE_VALUE", desc: "Net Sales Trend (Rs. Millions)",
        blocks: [{ type: "legend", items: ["Actual", "Target"] }, { type: "line", months: true }] },
      { n: 8, span: 8, title: "REQUIRED CORRECTIVE ACTIONS", icon: "doc",
        fields: "EMPLOYEE_NAME | PRODUCT_NO | CUST_NAME | DISCOUNTS",
        blocks: [{ type: "table", cols: ["#", "Area / Focus", "Issue / Observation", "Required Action", "Owner", "Timeline", "Status"], rows: 5 }] }
    ]
  },

  /* ============================ ASM ============================ */
  "ASM": {
    key: "asm",
    title: "ASM AREA PERFORMANCE DASHBOARD",
    subtitle: "Area Summary | Team Control | Product & Exception Management",
    kpis: [
      { label: "GROSS TP ACH.", icon: "bars", tone: "green", sub: "Actual / Target" },
      { label: "NET SALES ACH.", icon: "rupee", tone: "green", sub: "Actual / Target" },
      { label: "UNITS ACH.", icon: "cube", tone: "green", sub: "Actual / Target" },
      { label: "DISCOUNT % VS BUDGET", icon: "percent", tone: "red", sub: "Budget | variance" },
      { label: "ACTIVE MIO", icon: "window", tone: "blue", sub: "Target | Ach." },
      { label: "ACTIVE SPO", icon: "users", tone: "cyan", sub: "Target | Ach." },
      { label: "PRODUCTIVE SHOPS", icon: "shop", tone: "green", sub: "Target | Ach." }
    ],
    panels: [
      { n: 1, span: 4, title: "MIO & SPO NET SALES ACHIEVEMENT", icon: "bars",
        fields: "POSITION_CODE | EMPLOYEE_NAME | NET_SALE_VALUE", desc: "Team members ranked by Net Sales Achievement % (Individual columns for MIO & SPO)",
        blocks: [{ type: "dual", left: { title: "MIO Team Ach.", tone: "blue", rows: 5 }, right: { title: "SPO Team Ach.", tone: "green", rows: 5 } }] },
      { n: 2, span: 4, title: "VALUE PERFORMANCE — TARGET VS ACTUAL", icon: "bars",
        fields: "TP_SALE_VALUE | NET_SALE_VALUE | NET_QTY | NET_WO_REG_DISC_VALUE", desc: "Gross TP, Net Sales, Units and Net WO/Reg",
        blocks: [{ type: "legend", items: ["Target", "Actual"] },
                 { type: "columns", groups: ["Gross TP (Rs. M)", "Net Sales (Rs. M)", "Units (M)", "Net WO/Reg (Rs. M)"] },
                 { type: "note", text: "Compare key value and volume metrics against targets." }] },
      { n: 3, span: 4, title: "DISCOUNT, PROFITABILITY & EXCEPTIONS", icon: "percent",
        fields: "DISCOUNTS | TARGET ADDITIONAL DISCOUNT", desc: "Discount vs Budget and key exception indicators",
        blocks: [{ type: "budget" },
                 { type: "statCards", cols: 2, items: [{ label: "Critical SKUs", sub: "> 20% below target", icon: "alert", tone: "red" },
                                                       { label: "Low Margin SKUs", sub: "GM < 5%", icon: "tag", tone: "orange" },
                                                       { label: "Excess Discount SKUs", sub: "> Budget +2pp", icon: "percent", tone: "red" },
                                                       { label: "Non-Productive Shops", sub: "< 70% of target", icon: "shop", tone: "green" }] }] },

      { n: 4, span: 4, title: "PRODUCT PERFORMANCE — NET ACHIEVEMENT", icon: "cube",
        fields: "PRODUCT_NO | PRD_NAME | NET_SALE_VALUE", desc: "Bottom / Key products by Net Sales Achievement %",
        blocks: [{ type: "hbar", rows: 9, labelWide: true }] },
      { n: 5, span: 4, title: "AREA / TERRITORY TABLE", icon: "table",
        fields: "POSITION_CODE | EMPLOYEE_NAME | NET_SALE_VALUE | TP_SALE_VALUE | NET_QTY | TARGETS", desc: "Area wise performance summary",
        blocks: [{ type: "table", cols: ["#", "Area / Territory", "ASM", "MIO Count", "SPO Count", "Actual Net Sales", "Target Net Sales", "Ach. %"], rows: 8, dense: true }] },
      { n: 6, span: 4, title: "INSIGHTS & REQUIRED ACTIONS", icon: "bulb",
        blocks: [{ type: "numbered", rows: 4 }] },

      { n: 7, span: 12, title: "ASM CORRECTIVE ACTION PLAN", icon: "clip",
        fields: "POSITION_CODE | EMPLOYEE_NAME | PRODUCT_NO | DISCOUNTS | CHANNEL", desc: "Key actions, owners and timelines for performance improvement",
        blocks: [{ type: "form", fields: [{ label: "ASM / Area Comments", wide: true, area: true }, { label: "Action Owner" }, { label: "Timeline" }] }] }
    ]
  },

  /* ============================== MIO ============================== */
  "MIO": {
    key: "mio",
    title: "MIO FIELD PERFORMANCE DASHBOARD",
    subtitle: "Medical Information Officer | Individual Territory | Daily Execution | Doctor & Clinic Focus",
    kpis: [
      { label: "NET SALES ACH.", icon: "bars", tone: "green", sub: "Actual / Target" },
      { label: "UNITS ACH.", icon: "cube", tone: "blue", sub: "Actual / Target" },
      { label: "ACTIVE SHOPS", icon: "shop", tone: "orange", sub: "Target | Ach." },
      { label: "PRODUCTIVE SHOPS / COVERAGE %", icon: "users", tone: "green", sub: "Productive / Active" },
      { label: "NEW SHOPS ADDED", icon: "plus", tone: "blue", sub: "Target | Ach." },
      { label: "RETURNS VALUE", icon: "return", tone: "red", sub: "Value / Net Sales" }
    ],
    panels: [
      { n: 1, span: 4, title: "TOP CUSTOMERS / SHOPS", icon: "shop",
        desc: "Top / bottom shops by Net Sales Value (Rs.)", select: ["Top", "Bottom"],
        note: "Shows top 5 customers/shops by Net Sales Value for MIO.", fields: "CUST_NAME | CUST_NUMBER | NET_SALE_VALUE | Ach. % vs Target",
        blocks: [{ type: "hbar", rows: 5, sublabel: true }] },
      { n: 2, span: 4, title: "SKU PERFORMANCE — TARGET VS ACTUAL", icon: "cube",
        desc: "Top / bottom SKUs by achievement", select: ["Top", "Bottom"],
        note: "Shows top performing SKUs by Net Sales for MIO.", fields: "PRODUCT_NO | PRD_NAME | NET_SALE_VALUE | TARGET NET W/REG VALUE | Ach. %",
        blocks: [{ type: "legend", items: ["Target (Net Sales Value)", "Actual (Net Sales Value)"] },
                 { type: "hbar", rows: 6, sublabel: true, dual: true }] },
      { n: 3, span: 4, title: "MONTHLY TREND — NET SALES VS TARGET", icon: "trend",
        note: "Monthly trend of Net Sales with Target and Achievement %.", fields: "REPORTING_MONTH | NET_SALE_VALUE | TARGET NET W/REG VALUE",
        blocks: [{ type: "legend", items: ["Target (Rs.)", "Actual (Rs.)", "Achievement %"] },
                 { type: "line", months: true, bars: true }] },

      { n: 4, span: 4, title: "CHANNEL MIX", icon: "pie",
        desc: "Net Sales Value by Channel (Actual)", note: "Channel wise contribution to Net Sales (Pharmacies / Clinics).", fields: "CHANNEL | NET_SALE_VALUE",
        blocks: [{ type: "donut", legend: ["Pharmacies", "General Trade", "Hospitals", "Others"], center: "Total Net Sales", large: true }] },
      { n: 5, span: 4, title: "BEAT / AREA PERFORMANCE", icon: "pin",
        desc: "Territory / Area wise performance (Net Sales Value)", note: "Shows area/beat performance for the selected MIO.", fields: "AREA/BEAT | NET_SALE_VALUE | TARGET NET W/REG VALUE | Ach. %",
        blocks: [{ type: "table", cols: ["Area / Beat Name", "Type", "Actual (Rs.)", "Target (Rs.)", "Ach. %"], rows: 6, bars: true }] },
      { n: 6, span: 4, title: "ACTIONABLE INSIGHTS & NEXT STEPS", icon: "bulb", stack: true,
        blocks: [{ type: "numbered", rows: 4, tinted: true },
                 { type: "form", heading: "7. CORRECTIVE ACTION PLAN", fields: [{ label: "Enter corrective actions, clinic coverage and next steps…", wide: true, area: true }, { label: "Action owner" }, { label: "Timeline" }] }] }
    ]
  },

  /* ============================== SPO ============================== */
  "SPO": {
    key: "spo",
    title: "SPO FIELD PERFORMANCE DASHBOARD",
    subtitle: "Senior Promotion Officer | Individual Territory | Daily Execution | Retail & Trade Focus",
    kpis: [
      { label: "NET SALES ACHIEVEMENT %", icon: "bars", tone: "green", sub: "Actual / Target" },
      { label: "UNITS ACHIEVEMENT %", icon: "cube", tone: "blue", sub: "Actual / Target" },
      { label: "TARGET GAP", icon: "trend", tone: "orange", sub: "Target - Actual" },
      { label: "PRODUCTIVE SHOPS", icon: "shop", tone: "green", sub: "Positive net sales" },
      { label: "AVG. SALES / PRODUCTIVE SHOP", icon: "coin", tone: "cyan", sub: "Positive sales / shops" },
      { label: "RETURN RATE %", icon: "return", tone: "red", sub: "Return / positive gross" }
    ],
    panels: [
      { n: 1, span: 4, title: "TOP CUSTOMERS / SHOPS", icon: "shop",
        desc: "Top / bottom customer sales", select: ["Top", "Bottom"],
        note: "", fields: "",
        blocks: [{ type: "topCustomers" }] },
      { n: 2, span: 4, title: "SKU PERFORMANCE — TARGET VS ACTUAL", icon: "cube",
        desc: "Top / bottom SKU sales & achievement", select: ["Top", "Bottom"],
        note: "", fields: "",
        blocks: [{ type: "skuPerformance" }] },
      { n: 3, span: 4, title: "DISCOUNT PERFORMANCE", icon: "percent",
        select: ["Top", "Bottom"],
        fields: "",
        blocks: [{ type: "discount" }] },

      { n: 4, span: 4, title: "CALL DATA", icon: "phone", desc: "FMCG call activity",
        blocks: [{ type: "callPerformance" }] },
      { n: 5, span: 4, title: "ACTIONABLE INSIGHTS & NEXT STEPS", icon: "bulb",
        blocks: [{ type: "spoInsights" }] },
      { n: 6, span: 4, title: "CORRECTIVE ACTION PLAN", icon: "clip", stack: true,
        blocks: [{ type: "actionPlan" }] }
     ]
  }
};

// Backward-compatibility alias
// MIO uses the same field-force detail sections as SPO; only the identity text/accent differs.
DASHBOARDS["MIO"] = {
  ...DASHBOARDS["SPO"],
  key: "mio",
  title: "MIO FIELD PERFORMANCE DASHBOARD",
  subtitle: "Medical Information Officer | Individual Territory | Daily Execution | Doctor & Clinic Focus"
};
DASHBOARDS["MIO/SPO"] = DASHBOARDS["MIO"];

// Use the proven SPO/MIO card layout for every designation. The API scopes
// the same cards to the selected employee, territory, team or whole company.
const COMMON_FIELD_LAYOUT = {
  ...DASHBOARDS["SPO"],
  // Panel 4 is intentionally reserved for future call/activity data for
  // every designation. Product performance remains available in the SKU panel.
  panels: DASHBOARDS["SPO"].panels.map(p => ({ ...p }))
};
DASHBOARDS["ALL"] = {
  ...COMMON_FIELD_LAYOUT,
  key: "executive",
  title: "EXECUTIVE DASHBOARD",
  subtitle: "Overall Database | All Designations | Company-wide Sales Performance",
  kpis: [
    { label: "GROSS TP ACH.", icon: "bars", tone: "green", sub: "Actual / Target" },
    { label: "NET SALES ACH.", icon: "rupee", tone: "green", sub: "Actual / Target" },
    { label: "UNITS ACH.", icon: "cube", tone: "green", sub: "Actual / Target" },
    { label: "DISCOUNT % VS BUDGET", icon: "percent", tone: "red", sub: "Actual | Budget" },
    { label: "CYP ACH.", icon: "db", tone: "green", sub: "Actual / Target" }
  ]
};
DASHBOARDS["HOD"] = {
  ...COMMON_FIELD_LAYOUT,
  key: "hod",
  title: "HOD / NATIONAL EXECUTIVE DASHBOARD",
  subtitle: "National Summary | Strategic View | Executive Monitoring"
};
DASHBOARDS["RSM"] = {
  ...COMMON_FIELD_LAYOUT,
  key: "rsm",
  title: "RSM REGIONAL PERFORMANCE DASHBOARD",
  subtitle: "Regional Oversight | Team Performance | Target vs Actual"
};
DASHBOARDS["ASM"] = {
  ...COMMON_FIELD_LAYOUT,
  key: "asm",
  title: "ASM AREA PERFORMANCE DASHBOARD",
  subtitle: "Area Summary | Team Control | Product & Exception Management"
};

const FIELD_KPIS = [
  { label: "NET SALES ACHIEVEMENT %", icon: "rupee", tone: "green", sub: "Actual / Target" },
  { label: "UNITS ACHIEVEMENT %", icon: "cube", tone: "blue", sub: "Actual / Target" },
  { label: "TARGET GAP", icon: "trend", tone: "orange", sub: "Target - Actual" },
  { label: "ACTIVE SHOPS", icon: "shop", tone: "green", sub: "Positive net sales" },
  { label: "AVG. SALES / PRODUCTIVE SHOP", icon: "coin", tone: "cyan", sub: "Sales / productive shop" }
];
const ACTIVE_STAFF_KPI = {
  HOD: { label: "ACTIVE RSM", icon: "bars", tone: "violet", sub: "With sales / total RSM" },
  RSM: { label: "ACTIVE ASM", icon: "bars", tone: "violet", sub: "With sales / total ASM" },
  ASM: { label: "ACTIVE SPO/MIO", icon: "bars", tone: "violet", sub: "With sales / total SPO/MIO" }
};
["HOD", "RSM", "ASM"].forEach(key => {
  DASHBOARDS[key].kpis = [...FIELD_KPIS, ACTIVE_STAFF_KPI[key]];
});
const INDIVIDUAL_KPIS = [
  { label: "NET SALES ACHIEVEMENT %", icon: "rupee", tone: "green", sub: "Actual / Target" },
  { label: "UNITS ACHIEVEMENT %", icon: "cube", tone: "blue", sub: "Actual / Target" },
  { label: "ACTIVE SHOPS", icon: "shop", tone: "green", sub: "Positive net sales" },
  { label: "GOLM", icon: "trend", tone: "orange", sub: "Growth over last month" }
];
["MIO", "SPO"].forEach(key => { DASHBOARDS[key].kpis = INDIVIDUAL_KPIS; });
DASHBOARDS["ALL"].kpis = [
  { label: "NET SALES VALUE", icon: "rupee", tone: "green", sub: "Selected period actual" }
];

// Final designation layouts. These overrides intentionally come after the
// legacy templates above, which are kept for their reusable panel definitions.
const EXECUTIVE_ROLES = ["ALL", "EXEC", "HOD", "DGM"];
const FIELD_ROLES = ["SPO", "PS", "SB", "MIO", "ASMTE", "CM", "SPOWS", "TE"];
const standardKpis = [
  { label: "NET SALES ACHIEVEMENT %", icon: "rupee", tone: "green", sub: "Actual / target" },
  { label: "UNITS ACHIEVEMENT %", icon: "cube", tone: "blue", sub: "Actual / target" },
  { label: "TARGET GAP", icon: "trend", tone: "orange", sub: "Target minus actual" },
  { label: "ACTIVE SHOPS & COVERAGE %", icon: "shop", tone: "green", sub: "Selling / transacting shops" }
];
const growthKpi = { label: "GOLM", icon: "trend", tone: "cyan", sub: "Growth over last month" };
const managerPanels = COMMON_FIELD_LAYOUT.panels.map(panel => ({ ...panel }));
const fieldPanels = DASHBOARDS.SPO.panels.map(panel => ({ ...panel }));
const managerLayout = (key, title, lastKpi) => ({
  ...COMMON_FIELD_LAYOUT, key, title,
  kpis: [...standardKpis, growthKpi, lastKpi],
  panels: managerPanels.map(panel => ({ ...panel,
    title: panel.n === 1 ? (key === "rsm" ? "TOP ASM — ACHIEVEMENT %" : key === "asm" ? "TOP FIELD STAFF — ACHIEVEMENT %" : "TOP SALES POSITIONS — ACHIEVEMENT %") : panel.title
  }))
});
EXECUTIVE_ROLES.forEach(role => {
  DASHBOARDS[role] = managerLayout("executive", role === "ALL" ? "EXECUTIVE DASHBOARD" : `${role} EXECUTIVE DASHBOARD`,
    role === "ALL"
      ? { label: "DISCOUNT % VS BUDGET", icon: "percent", tone: "orange", sub: "Actual / budget discount" }
      : { label: "GROSS PROFIT MARGIN %", icon: "coin", tone: "violet", sub: "Requires actual COGS" });
});
DASHBOARDS.RSM = managerLayout("rsm", "RSM REGIONAL PERFORMANCE DASHBOARD",
  { label: "ACTIVE ASM", icon: "users", tone: "violet", sub: "With sales / total ASM" });
DASHBOARDS.ASM = managerLayout("asm", "ASM AREA PERFORMANCE DASHBOARD",
  { label: "ACTIVE FIELD STAFF", icon: "users", tone: "violet", sub: "SPO, PS, SB, MIO, ASMTE, CM, SPOWS, TE" });
FIELD_ROLES.forEach(role => {
  DASHBOARDS[role] = {
    ...DASHBOARDS.SPO, key: "field", title: `${role} FIELD PERFORMANCE DASHBOARD`,
    kpis: [...standardKpis,
      { label: "TOP CUSTOMER PERFORMANCE %", icon: "shop", tone: "cyan", sub: "Share of positive sales" },
      growthKpi],
    panels: fieldPanels.map(panel => ({ ...panel,
      title: panel.n === 1 ? "TOP CUSTOMERS / SHOPS PERFORMANCE %" : panel.title
    }))
  };
});

