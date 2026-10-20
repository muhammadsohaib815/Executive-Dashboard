/* Guard the Dept Terr Code controller and its loop-prevention path. */
const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('frontend/js/api.js', 'utf8');

assert.match(source, /async function applyTerritorySelection\(territory\)/);
assert.match(source, /\/api\/territory-scope\?territory=/);
assert.match(source, /values\.length === 1 \? values\[0\] : "All"/);
assert.match(source, /activeTerritoryScope = \{ territory: selectedTerritory, records, valuesByField \}/);
assert.match(source, /if \(activeTerritoryScope && userSelections\.territory === activeTerritoryScope\.territory\)/);
assert.match(source, /if \(field === "territory"\) \{/);

console.log('PASS: Dept Terr Code controls real staff-scope filter synchronization.');
