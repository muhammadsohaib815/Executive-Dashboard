/* Guard the original-style controls and safe insight rendering. */
const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('executive_website/static/js/ai-insights.js', 'utf8');

assert.match(source, /AI SALES INSIGHTS/);
assert.match(source, /Load Insights/);
assert.match(source, /data-ai-mode="employee"/);
assert.match(source, /data-ai-mode="product"/);
assert.match(source, /Designation <select id="aiDesignation"/);
assert.doesNotMatch(source, /id="aiProduct"/);
assert.doesNotMatch(source, /id="aiProductGroup"/);
assert.match(source, /replace\(\/\[&<>"'\]\//);
assert.match(source, /getJSON\('\/api\/meta\?team=COMBINED'\)/);
assert.match(source, /const inFlightRequests = new Map\(\)/);
assert.match(source, /related_total/);
assert.match(source, /designation: 'ALL'/);
assert.doesNotMatch(source, /resetForDashboardFilters/);
assert.doesNotMatch(source, /document\.addEventListener\('filters:apply'/);
assert.doesNotMatch(source, /\$\('fName'\)\?\.value/);
assert.doesNotMatch(source, /\$\('fRegion'\)\?\.value/);
assert.doesNotMatch(source, /\$\('fTeam'\)\?\.value/);
assert.match(source, /pageSize: 20/);
assert.match(source, /offset: state.pageOffset/);
assert.match(source, /loadInsights\(true\)/);

console.log('PASS: AI controls are independent from dashboard filters.');
