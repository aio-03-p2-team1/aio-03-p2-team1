import { test } from 'node:test'
import assert from 'node:assert/strict'
import { textOverflows } from '../src/lib/posterText.js'

const measure = (text) => Array.from(text).length * 10

test('text fits when wrapped lines stay inside the selected component height', () => {
  assert.equal(textOverflows({ content: '보리', width: 100, height: 30, fontSize: 20, padding: 0 }, measure), false)
  assert.equal(textOverflows({ content: '우리 아이 보리를 찾습니다', width: 100, height: 60, fontSize: 20, padding: 0 }, measure), false)
})

test('text overflow warns for wrapped lines and explicit newlines', () => {
  assert.equal(textOverflows({ content: '우리 아이 보리를 찾습니다', width: 100, height: 30, fontSize: 20, padding: 0 }, measure), true)
  assert.equal(textOverflows({ content: '첫 줄\n둘째 줄', width: 200, height: 35, fontSize: 20, padding: 0 }, measure), true)
  assert.equal(textOverflows({ content: '', width: 100, height: 10, fontSize: 20 }, measure), false)
})
