import { test } from 'node:test'
import assert from 'node:assert/strict'
import { matchRegion, shortRegion } from '../src/lib/region.js'

const REGIONS = [
  { code: '6110000', name: '서울특별시' },
  { code: '6410000', name: '경기도' },
  { code: '6530000', name: '강원특별자치도' },
  { code: '6480000', name: '경상남도' }
]

test('kakao sido names map to official region names', () => {
  assert.equal(matchRegion('서울특별시', REGIONS), '서울특별시')
  assert.equal(matchRegion('서울', REGIONS), '서울특별시')
  assert.equal(matchRegion('강원도', REGIONS), '강원특별자치도')
  assert.equal(matchRegion('경남', REGIONS), '경상남도')
})

test('unknown or empty region is not guessed', () => {
  assert.equal(matchRegion('제주특별자치도', REGIONS), null)
  assert.equal(matchRegion('', REGIONS), null)
  assert.equal(shortRegion('충청북도'), '충북')
})
