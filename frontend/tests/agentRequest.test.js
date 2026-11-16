import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addAnswer, answerChips, applyAnswers, removeAnswer, visibleRequest } from '../src/lib/agentRequest.js'

const info = { type: 'info', field: 'color', label: '털색', options: ['흰색', '갈색'], reason: '털색을 알려 주세요.' }

test('request hidden when declined, answered, or still awaiting input', () => {
  const run = { status: 'completed', agent_request: info }
  assert.equal(visibleRequest(run), info)
  assert.equal(visibleRequest(run, {}, ['color']), null)
  assert.equal(visibleRequest(run, { color: ['흰색'] }), null)
  assert.equal(visibleRequest({ ...run, status: 'awaiting_input' }), null)
  assert.equal(visibleRequest({ status: 'completed', agent_request: { type: 'photo', reason: 'x' } }, {}, ['photo']), null)
})

test('answers become chips and merge into criteria without rewriting description', () => {
  let answers = addAnswer({}, 'color', '흰색')
  answers = addAnswer(answers, 'color', '갈색')
  answers = addAnswer(answers, 'size', '소형')
  answers = addAnswer(answers, 'size', '중형') // 크기는 하나만
  answers = addAnswer(answers, 'sex', '암컷')
  answers = addAnswer(answers, 'marks', '얼룩·점')
  assert.deepEqual(answerChips(answers).map((c) => c.label), ['털색: 흰색', '털색: 갈색', '크기: 중형', '성별: 암컷', '특징: 얼룩·점'])
  const criteria = applyAnswers({ description: '믹스견' }, answers)
  assert.deepEqual(criteria, { description: '믹스견\n추가 특징: 얼룩·점', color: '흰색 갈색', size: '중형', sex: 'F' })
  assert.deepEqual(removeAnswer(answers, 'size', '중형').size, undefined)
})
