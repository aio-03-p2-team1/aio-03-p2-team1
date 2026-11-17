import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fillPoster, koreanDate, postToPosterFields, setPosterPhoto } from '../src/lib/postPoster.js'

test('member post fills poster fields and keeps contact for the user', () => {
  const fields = postToPosterFields({
    source: 'member', pet_name: '초코', species: 'dog', breed: '푸들', region: '서울특별시', lost_place: '강서구 화곡동',
    lost_date: '2026-11-14', description: '갈색 작은 강아지, 노란 목줄',
  })
  assert.equal(fields.title, '초코를 찾습니다')
  assert.equal(fields.pet_name, '초코')
  assert.equal(fields.species_breed, '강아지 · 푸들')
  assert.equal(fields.lost_datetime, '2026년 11월 14일')
  assert.equal(fields.lost_place, '강서구 화곡동')
  assert.equal(fields.features, '갈색 작은 강아지, 노란 목줄')
  assert.equal('contact' in fields, false)
  assert.equal('extra_description' in fields, false)
})

test('lost report without a name uses breed title and facts', () => {
  const fields = postToPosterFields({
    source: 'lost_api', species: 'cat', breed: '코리안숏헤어', color: '치즈', sex: 'F', age: '2023(년생)',
    region: '경기도 수원시', happen_place: '영통구 매탄동', lost_date: '2026-11-10', description: 'x'.repeat(200),
  })
  assert.equal(fields.title, '코리안숏헤어를 찾습니다')
  assert.equal(fields.pet_name, '이름 미상')
  assert.equal(fields.lost_place, '영통구 매탄동')
  assert.ok(fields.features.startsWith('털색 치즈, 암컷, 나이 2023(년생) / '))
  assert.ok(fields.features.length <= 120 && fields.features.endsWith('…'))
  assert.ok(fields.extra_description)
  assert.equal(koreanDate('bad'), '')
})

test('fillPoster replaces only matching text fields and setPosterPhoto fills the first image slot', () => {
  const poster = {
    templateId: 'basic', width: 794, height: 1123,
    components: [
      { id: 't', type: 'text', fieldKey: 'title', content: '강아지를 찾습니다' },
      { id: 'c', type: 'text', fieldKey: 'contact', content: '연락처를 입력해 주세요' },
      { id: 'p1', type: 'image', assetId: null },
      { id: 'p2', type: 'image', assetId: null },
    ],
  }
  const filled = setPosterPhoto(fillPoster(poster, { title: '보리를 찾습니다' }), 'a'.repeat(32))
  assert.equal(filled.components[0].content, '보리를 찾습니다')
  assert.equal(filled.components[1].content, '연락처를 입력해 주세요')
  assert.equal(filled.components[2].assetId, 'a'.repeat(32))
  assert.equal(filled.components[3].assetId, null)
  assert.equal(poster.components[0].content, '강아지를 찾습니다') // 원본은 그대로
})
