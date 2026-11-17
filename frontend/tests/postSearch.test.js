import { test } from 'node:test'
import assert from 'node:assert/strict'
import { postToSearch, savePostSearch, takePostSearch } from '../src/lib/postSearch.js'

const TODAY = '2026-11-16'

test('member post fills species, sido, address, date and description', () => {
  const v = postToSearch({ id: 'p1', pet_name: '초코', species: 'dog', region: '서울특별시', lost_place: '서울특별시 강서구 화곡동',
    lost_date: '2026-11-10', breed: '푸들', description: '갈색, 빨간 목줄' }, TODAY)
  assert.deepEqual(v.form, { breed_code: '', species: 'dog', lost_date: '2026-11-10', description: '품종: 푸들\n갈색, 빨간 목줄' })
  assert.deepEqual(v.location, { region: '서울특별시', address: '서울특별시 강서구 화곡동' })
  assert.equal(v.source.title, '초코')
})

test('lost report uses first word of region, facts and last seen place; bad date becomes today', () => {
  const v = postToSearch({ id: 'L1', source: 'lost_api', species: 'cat', region: '경기도 수원시', lost_place: '',
    happen_place: '공원 앞', lost_date: '2026-12-01', breed: '코리안 숏헤어', color: '흰색', sex: 'F', age: '2024(년생)',
    description: '' }, TODAY)
  assert.equal(v.form.lost_date, TODAY)
  assert.deepEqual(v.location, { region: '경기도', address: '경기도 수원시' })
  assert.equal(v.form.description, '품종: 코리안 숏헤어, 털색: 흰색, 성별: 암컷, 나이: 2024(년생)\n마지막으로 본 장소: 공원 앞')
  assert.equal(postToSearch({ species: 'bird' }, TODAY).form.species, '')
  assert.equal(postToSearch({}, TODAY).location, null)
})

test('handoff is read once', () => {
  const store = new Map()
  const storage = { setItem: (k, v) => store.set(k, v), getItem: (k) => store.get(k) ?? null, removeItem: (k) => store.delete(k) }
  savePostSearch({ form: { species: 'dog' } }, storage)
  assert.deepEqual(takePostSearch(storage), { form: { species: 'dog' } })
  assert.equal(takePostSearch(storage), null)
})
