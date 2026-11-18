import test from 'node:test'
import assert from 'node:assert/strict'
import { inputReviewView } from '../src/lib/inputReview.js'

const review = {
  action: 'search',
  message: '흰색이 글과 사진에 겹쳐 하나로 합쳤어요.',
  question: '',
  duplicates: ['흰색(글과 사진)'],
  conflicts: [{ item: '털색', text_value: '흰색', photo_value: '갈색' }],
  organized_text: '[털색]: 흰색\n[특징]: 빨간 목줄',
}

test('input review shows the judgment, merged duplicates and conflicts', () => {
  const view = inputReviewView(review, '흰색 강아지')
  assert.equal(view.title, '에이전트가 입력을 정리했어요')
  assert.equal(view.message, review.message)
  assert.deepEqual(view.lines, [
    '합친 중복: 흰색(글과 사진)',
    '어긋난 정보: 털색 — 글 흰색 / 사진 갈색 (글 기준으로 찾아요)',
  ])
  assert.equal(view.canApply, true)
  assert.equal(view.question, '')
})

test('organized text already in the input is not offered again', () => {
  assert.equal(inputReviewView(review, '[털색]: 흰색\n[특징]: 빨간 목줄 ').canApply, false)
})

test('ask action exposes the question and missing review shows nothing', () => {
  const view = inputReviewView({ ...review, action: 'ask', question: '어느 색이 맞나요?' })
  assert.equal(view.title, '에이전트가 먼저 확인할게요')
  assert.equal(view.question, '어느 색이 맞나요?')
  assert.equal(inputReviewView(null), null)
  assert.equal(inputReviewView({ action: 'search', message: '' }), null)
})
