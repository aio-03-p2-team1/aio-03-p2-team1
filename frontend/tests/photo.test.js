import { test } from 'node:test'
import assert from 'node:assert/strict'
import { photoAnalysisError, photoSelectionError, unsuitablePhotoMessage } from '../src/lib/photo.js'

test('photo selection accepts supported formats and rejects unsupported formats', () => {
  for (const type of ['image/jpeg', 'image/png', 'image/webp']) {
    assert.equal(photoSelectionError({ type, size: 1024 }), '')
  }
  assert.equal(photoSelectionError({ type: 'image/gif', size: 1024 }), 'JPG, PNG, WEBP 형식의 사진만 사용할 수 있어요.')
})

test('photo selection reports the existing 8MB limit', () => {
  assert.equal(photoSelectionError({ type: 'image/jpeg', size: 8 * 1024 * 1024 }), '')
  assert.equal(photoSelectionError({ type: 'image/jpeg', size: 8 * 1024 * 1024 + 1 }), '사진은 8MB 이하로 선택해 주세요.')
})

test('photo analysis errors distinguish photo format from request failures', () => {
  for (const code of ['invalid_photo', 'unsupported_photo_format']) {
    assert.equal(photoAnalysisError({ code }), 'JPG, PNG, WEBP 형식의 사진만 사용할 수 있어요.')
  }
  assert.equal(photoAnalysisError({ code: 'network' }), '오류가 발생했습니다.')
  assert.equal(photoAnalysisError({ code: 'llm_unavailable' }), '오류가 발생했습니다.')
})

test('unsuitable photo maps its reason code to guidance', () => {
  const reasons = ['animal_not_detected', 'appearance_unclear', 'subject_not_distinct']
  const messages = reasons.map((reason_code) => unsuitablePhotoMessage({ suitable: false, reason_code }))
  assert.ok(messages.every(Boolean))
  assert.equal(new Set(messages).size, reasons.length)

  const fallback = unsuitablePhotoMessage({ suitable: false, reason_code: 'unknown_reason' })
  assert.ok(fallback)
  assert.ok(!messages.includes(fallback))
  assert.equal(unsuitablePhotoMessage({ suitable: true, reason_code: 'animal_not_detected' }), '')
})
