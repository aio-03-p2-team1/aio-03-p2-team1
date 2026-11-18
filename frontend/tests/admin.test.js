import { test } from 'node:test'
import assert from 'node:assert/strict'
import { counterRows, number, percent, runsToCsv, statLabel, tabFromSearch } from '../src/lib/admin.js'

test('tabFromSearch falls back to overview for unknown tabs', () => {
  assert.equal(tabFromSearch('?tab=logs'), 'logs')
  assert.equal(tabFromSearch('?tab=evil'), 'overview')
  assert.equal(tabFromSearch(''), 'overview')
})

test('counterRows sorts by count and computes shares with labels', () => {
  const rows = counterRows({ duplicates: 1, few_features: 3, unknown_code: 0 })
  assert.deepEqual(rows.map((r) => r.key), ['few_features', 'duplicates', 'unknown_code'])
  assert.equal(rows[0].label, '입력 특징 1개 이하')
  assert.equal(rows[0].share, 0.75)
  assert.equal(statLabel('custom'), 'custom')
  assert.deepEqual(counterRows(null), [])
})

test('percent and number show 미측정 for missing values', () => {
  assert.equal(percent(0.1234), '12.3%')
  assert.equal(percent(null), '미측정')
  assert.equal(number(1200, 'ms'), '1,200ms')
  assert.equal(number(undefined), '미측정')
})

test('runsToCsv escapes quotes, commas and formula prefixes', () => {
  const csv = runsToCsv([{ email: 'a@x.com', error: '=cmd()', issues: ['duplicates', 'tool_error'], status: 'ok, "x"' }],
    ['email', 'status', 'issues', 'error'])
  const [head, row] = csv.split('\n')
  assert.equal(head, 'email,status,issues,error')
  assert.equal(row, 'a@x.com,"ok, ""x""",duplicates|tool_error,\'=cmd()')
})
