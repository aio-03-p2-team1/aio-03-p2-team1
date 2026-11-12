import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  errorMessage,
  formatDate,
  kakaoSearchUrl,
  scopeText,
  sexLabel,
  sourceLabel,
  speciesLabel,
  telHref
} from '../src/lib/format.js'

test('labels fall back to 미확인 instead of guessing', () => {
  assert.equal(speciesLabel('dog'), '개')
  assert.equal(speciesLabel('???'), '미확인')
  assert.equal(sexLabel('F'), '암컷')
  assert.equal(sexLabel(undefined), '미확인')
  assert.equal(formatDate('2026-11-10'), '2026.11.10')
  assert.equal(formatDate(null), '미확인')
})

test('source label distinguishes real API data from samples', () => {
  assert.equal(sourceLabel('api'), '실제 공고 데이터')
  assert.equal(sourceLabel('sample'), '샘플 데이터')
})

test('scope text states partial coverage honestly', () => {
  const partial = scopeText({ region: '서울특별시', species: 'dog', start_date: '2026-11-01', end_date: '2026-11-12', complete: false, total_count: 400, fetched_rows: 150 })
  assert.match(partial, /400건 중 150건만 조회/)
  const full = scopeText({ region: 'all', species: 'all', start_date: '2026-11-01', end_date: '2026-11-12', complete: true, total_count: 3 })
  assert.match(full, /^전체 지역 · 전체/)
  assert.match(full, /3건 확인/)
})

test('tel link only for real-looking numbers', () => {
  assert.equal(telHref('02-123-4567'), 'tel:021234567')
  assert.equal(telHref(''), null)
  assert.equal(telHref('미상'), null)
})

test('kakao link encodes address', () => {
  assert.equal(kakaoSearchUrl('서울 강서구'), 'https://map.kakao.com/link/search/%EC%84%9C%EC%9A%B8%20%EA%B0%95%EC%84%9C%EA%B5%AC')
  assert.equal(kakaoSearchUrl(null), null)
})

test('error message prefers server message then code table', () => {
  assert.equal(errorMessage({ code: 'x', message: '서버 메시지' }), '서버 메시지')
  assert.match(errorMessage({ code: 'network' }), /연결하지 못했습니다/)
  assert.equal(errorMessage(null), '')
})
