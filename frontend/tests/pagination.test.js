import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cachedPage, pageNumber, rememberPage } from '../src/lib/pagination.js'

test('URL pages are positive integers', () => {
  for (const value of [null, '-1', 'NaN', '1.5', 'Infinity']) assert.equal(pageNumber(value), 1)
  assert.equal(pageNumber('15'), 15)
})

test('back navigation can reuse the same page for ten minutes and evicts bounded old pages', () => {
  let cache = rememberPage({}, 'run:2', { candidates: ['21'] }, 100)
  assert.deepEqual(cachedPage(cache, 'run:2', 200), { candidates: ['21'] })
  assert.equal(cachedPage(cache, 'run:2', 600100), null)
  for (let i = 0; i < 60; i++) cache = rememberPage(cache, `run:${i}`, i, 200)
  assert.equal(Object.keys(cache).length, 45)
})
