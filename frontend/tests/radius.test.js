import { test } from 'node:test'
import assert from 'node:assert/strict'
import { distanceLabel, kmLabel, radiusText, widenRadiusAction } from '../src/lib/radius.js'

const applied = { applied: true, auto: false, step: 1, radius_km: 10, inside: 4, unknown: 1, excluded: 7, lost_place: '서울특별시 강서구 화곡동' }

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


test('widen action reads next step from the radius question', () => {
  const action = widenRadiusAction([{ field: 'radius', next_step: 2, message: '...' }], applied)
  assert.deepEqual(action, { step: 2, label: '반경 20km로 넓혀 찾기', from: 10 })
  assert.equal(widenRadiusAction([{ field: 'region', message: '...' }], applied), null)
  assert.equal(widenRadiusAction([{ field: 'radius', next_step: 3 }], applied).label, '조회 지역 전체로 넓혀 찾기')
})

test('distance label distinguishes unknown from no radius', () => {
  assert.equal(distanceLabel({ distance_basis: 'jurisdiction_center', distance_km: 2.4 }), '약 2.4km(관할 기준)')
  assert.equal(distanceLabel({ distance_basis: 'rescue_area', distance_km: 0.3 }), '약 0.3km(구조 장소 기준)')
  assert.equal(distanceLabel({ distance_basis: 'unknown', distance_km: null }), '거리 미확인')
  assert.equal(distanceLabel({}), '')
  assert.equal(kmLabel(null), '조회 지역 전체')
})

// ── 실종 후 경과일 안내와 검색 전 미리 보기 ─────────────────────
import { daysSince, nextWidenDay, previewRadius, RADIUS_STEPS_KM, radiusGuide, recommendedStep, STEP_BY_DAYS } from '../src/lib/radius.js'
import { readFileSync } from 'node:fs'

test('preview step table matches the server table', () => {
  // 서버 기준표와 어긋나면 미리 보기와 실제 검색 범위가 달라진다.
  const py = readFileSync(new URL('../../backend/agent/radius.py', import.meta.url), 'utf8')
  const steps = py.match(/RADIUS_STEPS_KM[^=]*=\s*\(([^)]*)\)/)[1].split(',').map((v) => v.trim()).filter(Boolean)
  assert.deepEqual(steps.map((v) => (v === 'None' ? null : Number(v))), RADIUS_STEPS_KM)
  const days = [...py.match(/STEP_BY_DAYS\s*=\s*\((.*)\)\n/)[1].matchAll(/\((\d+),\s*(\d+)\)/g)].map((m) => [Number(m[1]), Number(m[2])])
  assert.deepEqual(days, STEP_BY_DAYS)
})

test('days since lost and recommended step follow the table', () => {
  assert.equal(daysSince('2026-11-13', '2026-11-16'), 3)
  assert.equal(daysSince('잘못된 날짜', '2026-11-16'), null)
  assert.deepEqual([0, 3, 4, 7, 8, 14, 15].map(recommendedStep), [0, 0, 1, 1, 2, 2, 3])
  assert.equal(nextWidenDay(0), 4)
  assert.equal(nextWidenDay(2), 15)
  assert.equal(nextWidenDay(3), null)
})

test('preview radius needs a picked point and a date', () => {
  const location = { region: '서울특별시', address: '서울특별시 마포구 망원동', lat: 37.556, lng: 126.904 }
  const p = previewRadius(location, '2026-11-11', '2026-11-16')
  assert.equal(p.radius_km, 10)
  assert.equal(p.days_since_lost, 5)
  assert.deepEqual(p.center, { lat: 37.556, lng: 126.904 })
  assert.equal(previewRadius({ region: '서울특별시', address: '서울' }, '2026-11-11', '2026-11-16'), null) // 좌표 없음
  assert.equal(previewRadius({ ...location, region: '전체' }, '2026-11-11', '2026-11-16'), null)
  assert.equal(previewRadius(location, '2026-11-20', '2026-11-16'), null) // 미래 날짜
  assert.equal(previewRadius(location, '2026-10-01', '2026-11-16').radius_km, null) // 2주 넘음 → 전체
})

test('guide text explains days and the next widening day', () => {
  assert.deepEqual(radiusGuide({ days_since_lost: 5, radius_km: 10, step: 1, auto: true, next_widen_day: 8 }),
    ['실종 후 5일이 지났어요. 실종 위치에서 10km 안을 찾아요.', '실종 후 8일이 지나면 20km로 넓혀 찾아요.'])
  assert.deepEqual(radiusGuide({ days_since_lost: 0, radius_km: 3, step: 0, auto: true, next_widen_day: 4 })[0],
    '오늘 실종됐어요. 실종 위치에서 3km 안을 찾아요.')
  assert.equal(radiusGuide({ days_since_lost: 10, radius_km: 20, step: 2, auto: true, next_widen_day: 15 })[1],
    '실종 후 15일이 지나면 조회 지역 전체에서 찾아요.')
  assert.deepEqual(radiusGuide({ days_since_lost: 2, radius_km: 10, step: 1, auto: false, next_widen_day: null }),
    ['넓히기를 선택해 실종 위치에서 10km 안을 찾아요.', ''])
  assert.match(radiusGuide({ days_since_lost: 20, radius_km: null })[0], /조회 지역 전체/)
})

