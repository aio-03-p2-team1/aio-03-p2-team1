import { test } from 'node:test'
import assert from 'node:assert/strict'
import { distanceLabel, kmLabel, previousRadiusKm, radiusText, widenRadiusAction } from '../src/lib/radius.js'

const applied = { applied: true, step: 1, radius_km: 10, inside: 4, unknown: 1, excluded: 7, lost_place: '서울특별시 강서구 화곡동' }

test('radius summary shows counts and basis', () => {
  const text = radiusText(applied)
  assert.ok(text.includes('10km 안'))
  assert.ok(text.includes('4건'))
  assert.ok(text.includes('거리 미확인 1건'))
  assert.ok(text.includes('반경 밖 7건 제외'))
  assert.ok(text.includes('직선거리'))
})

test('not applied radius explains why', () => {
  assert.ok(radiusText({ applied: false, reason: 'whole_region' }).includes('전체'))
  assert.equal(radiusText({ applied: false, reason: 'not_configured', reason_text: '지도 키가 없어 반경을 적용하지 않음' }), '지도 키가 없어 반경을 적용하지 않음.')
  assert.equal(radiusText(null), '')
})

test('previous ring only after widening', () => {
  assert.equal(previousRadiusKm(applied), 3)
  assert.equal(previousRadiusKm({ ...applied, step: 0 }), null)
  assert.equal(previousRadiusKm({ applied: false, step: 2 }), null)
})

test('widen action reads next step from the radius question', () => {
  const action = widenRadiusAction([{ field: 'radius', next_step: 2, message: '...' }], applied)
  assert.deepEqual(action, { step: 2, label: '반경 20km로 넓혀 찾기', from: 10 })
  assert.equal(widenRadiusAction([{ field: 'region', message: '...' }], applied), null)
  assert.equal(widenRadiusAction([{ field: 'radius', next_step: 3 }], applied).label, '조회 지역 전체로 넓혀 찾기')
})

test('distance label distinguishes unknown from no radius', () => {
  assert.equal(distanceLabel({ distance_basis: 'jurisdiction_center', distance_km: 2.4 }), '약 2.4km(관할 기준)')
  assert.equal(distanceLabel({ distance_basis: 'unknown', distance_km: null }), '거리 미확인')
  assert.equal(distanceLabel({}), '')
  assert.equal(kmLabel(null), '조회 지역 전체')
})
