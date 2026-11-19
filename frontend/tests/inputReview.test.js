import test from 'node:test'
import assert from 'node:assert/strict'
import { applyPhotoValue, conflictChoices, inputReviewView, kindCheckText } from '../src/lib/inputReview.js'

const review = {
  action: 'search',
  message: '흰색이 글과 사진에 겹쳐 하나로 합쳤어요.',
  question: '',
  duplicates: ['흰색(글과 사진)'],
  conflicts: [{ item: '털색', text_value: '흰색', photo_value: '갈색' }],
  organized_text: '[털색]: 흰색\n[특징]: 빨간 목줄',
}

test('input review shows the judgment, merged duplicates, conflicts and that the text was rewritten', () => {
  const view = inputReviewView(review)
  assert.equal(view.title, '에이전트가 입력을 정리했어요')
  assert.equal(view.message, review.message)
  assert.deepEqual(view.lines, [
    '합친 중복: 흰색(글과 사진)',
    '어긋난 정보: 털색 — 글 흰색 / 사진 갈색 (글 기준으로 찾아요)',
    '특징과 상황을 정리한 글로 바꿨어요.',
  ])
  assert.equal(view.question, '')
})

test('ask action exposes the question and missing review shows nothing', () => {
  const view = inputReviewView({ ...review, action: 'ask', question: '어느 색이 맞나요?' })
  assert.equal(view.title, '에이전트가 먼저 확인할게요')
  assert.equal(view.question, '어느 색이 맞나요?')
  assert.equal(inputReviewView(null), null)
  assert.equal(inputReviewView({ action: 'search', message: '' }), null)
})

test('filters from the text come first in the review lines', () => {
  const view = inputReviewView({ ...review, filters: ["글에 '푸들'이(가) 있어 푸들 계열만 찾아요."] })
  assert.equal(view.lines[0], "글에 '푸들'이(가) 있어 푸들 계열만 찾아요.")
})

test('kind check summary explains what was kept and dropped', () => {
  assert.equal(
    kindCheckText({ target: '새', checked: 12, kept: 3, kept_by_text: 1, kept_by_photo: 2, other_kind: 7, unknown: 2 }),
    '기타 동물 12건 중 새로 확인된 공고 3건 (글 1건 · 사진 2건) · 제외: 다른 동물 7건, 종류를 확인하지 못한 2건',
  )
  assert.equal(kindCheckText({ target: '새', checked: 4, kept: 0, kept_by_text: 0, kept_by_photo: 0, other_kind: 4, unknown: 0 }),
    '기타 동물 4건 중 새로 확인된 공고 0건 · 제외: 다른 동물 4건')
  assert.equal(kindCheckText(null), '')
})

test('a generic text value is filled in with the photo detail', () => {
  const text = '[털색]: 기타\n[특징]: 목 깃털 물결무늬'
  const conflict = { item: '털색', text_value: '기타', photo_value: '회색, 검정, 빨강' }
  assert.equal(applyPhotoValue(text, conflict), '[털색]: 기타: 회색, 검정, 빨강\n[특징]: 목 깃털 물결무늬')
  assert.deepEqual(conflictChoices(conflict).map((c) => c.label), ['사진 분석 털색 넣기: 기타: 회색, 검정, 빨강', '입력한 털색 그대로: 기타'])
})

test('a different text value offers text or photo and replaces the line', () => {
  const conflict = { item: '털색', text_value: '갈색', photo_value: '흰색' }
  assert.equal(applyPhotoValue('[털색]: 갈색', conflict), '[털색]: 흰색')
  assert.deepEqual(conflictChoices(conflict).map((c) => [c.side, c.label]), [['text', '입력한 털색: 갈색'], ['photo', '사진 분석 털색: 흰색']])
})

test('a missing item line is appended once', () => {
  const conflict = { item: '성별', text_value: '수컷', photo_value: '암컷' }
  assert.equal(applyPhotoValue('[털색]: 흰색\n', conflict), '[털색]: 흰색\n[성별]: 암컷')
  assert.equal(applyPhotoValue('', conflict), '[성별]: 암컷')
  assert.equal(applyPhotoValue('그대로', { item: '털색', photo_value: '' }), '그대로')
  assert.deepEqual(conflictChoices({ item: '털색', text_value: '기타', photo_value: '' }), [])
})
