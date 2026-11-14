import { test } from 'node:test'
import assert from 'node:assert/strict'
import { boardSummary, dataUrlBytes, isLostReport, postPath, postPhotoPath, postSpeciesLabel, postTitle, sexLabel, validatePost } from '../src/lib/post.js'

const TODAY = '2026-11-13'
const ok = {
  pet_name: '초코',
  species: 'dog',
  region: '서울특별시',
  lost_date: '2026-11-10',
  breed: '푸들',
  description: '갈색 작은 강아지, 노란 목줄'
}

test('valid post has no errors', () => {
  assert.deepEqual(validatePost(ok, TODAY), {})
})

test('required fields are reported', () => {
  const errors = validatePost({ pet_name: ' ', description: '짧음' }, TODAY)
  assert.deepEqual(Object.keys(errors).sort(), ['description', 'lost_date', 'pet_name', 'region', 'species'])
})

test('future and too-old dates are rejected', () => {
  assert.ok(validatePost({ ...ok, lost_date: '2026-11-14' }, TODAY).lost_date.includes('이후'))
  assert.ok(validatePost({ ...ok, lost_date: '2025-11-01' }, TODAY).lost_date.includes('1년'))
  assert.equal(validatePost({ ...ok, lost_date: TODAY }, TODAY).lost_date, undefined)
})

test('location must be picked on the map (not 전체)', () => {
  assert.ok(validatePost({ ...ok, region: '전체' }, TODAY).region.includes('지도'))
  assert.ok(validatePost({ ...ok, lost_place: 'x'.repeat(101) }, TODAY).region)
  assert.equal(validatePost({ ...ok, lost_place: '서울특별시 강서구 화곡동' }, TODAY).region, undefined)
})

test('species must be a concrete kind (not 전체)', () => {
  assert.ok(validatePost({ ...ok, species: 'all' }, TODAY).species)
  assert.equal(postSpeciesLabel('cat'), '고양이')
  assert.equal(postSpeciesLabel('x'), '미확인')
})

test('data url byte size and helpers', () => {
  assert.equal(dataUrlBytes('data:image/png;base64,AAAA'), 3)
  assert.equal(dataUrlBytes('data:image/png;base64,AAA='), 2)
  assert.equal(dataUrlBytes('nope'), 0)
  assert.equal(postPhotoPath('ab/c'), '/posts/ab%2Fc/photo')
  assert.equal(postTitle({ pet_name: '초코' }), '초코를 찾습니다')
  assert.equal(postTitle({ pet_name: '보름' }), '보름을 찾습니다')
  assert.equal(postTitle({ pet_name: 'Max' }), 'Max을(를) 찾습니다')
})

test('lost reports link to their own detail path and get a breed title', () => {
  const lost = { id: 'lost-20261111-0123456789ab', source: 'lost_api', pet_name: '', breed: '믹스견', species: 'dog' }
  assert.equal(isLostReport(lost), true)
  assert.equal(postPath(lost), '/board/lost/lost-20261111-0123456789ab')
  assert.equal(postPath({ id: 'a'.repeat(32), source: 'member' }), `/board/${'a'.repeat(32)}`)
  assert.equal(postTitle(lost), '믹스견을 찾습니다')
  assert.equal(postTitle({ pet_name: '', breed: '', species: 'cat' }), '고양이를 찾습니다')
  assert.equal(sexLabel('F'), '암컷')
  assert.equal(sexLabel('Q'), '')
})

test('board summary separates member posts and public lost reports', () => {
  assert.equal(boardSummary({ count: 5, member_count: 1, lost_count: 4, lost: { status: 'ok' } }),
    '조건에 맞는 글 5건 (회원 글 1건 · 공공데이터 분실 신고 4건)')
  assert.equal(boardSummary({ count: 1, lost: { status: 'unavailable' } }), '조건에 맞는 글 1건')
})
