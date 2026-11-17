import { test } from 'node:test'
import assert from 'node:assert/strict'
import { usePosterStore } from '../src/lib/posterStore.js'

const initial = {
  templateId: 'basic', width: 794, height: 1123,
  components: [{ id: 'title', type: 'text', content: '찾습니다', x: 20, y: 30, width: 400, height: 60, fontSize: 32 }]
}

test('poster text changes preserve position and design properties', () => {
  const store = usePosterStore.getState()
  store.setPoster(initial)
  store.updateComponent('title', { content: '보리를 찾습니다' })
  const item = usePosterStore.getState().poster.components[0]
  assert.equal(item.content, '보리를 찾습니다')
  assert.deepEqual([item.x, item.y, item.width, item.height, item.fontSize], [20, 30, 400, 60, 32])
})

test('added text is editable and deletion removes the paired component', () => {
  const store = usePosterStore.getState()
  store.setPoster(initial)
  store.addComponent({ id: 'new-text', type: 'text', label: '추가 문구', content: '내용' })
  assert.equal(usePosterStore.getState().poster.components.length, 2)
  assert.equal(usePosterStore.getState().selectedId, 'new-text')
  store.removeComponent('new-text')
  assert.deepEqual(usePosterStore.getState().poster.components.map((item) => item.id), ['title'])
})

test('undo and redo restore document snapshots', () => {
  const store = usePosterStore.getState()
  store.setPoster(initial)
  store.updateComponent('title', { content: '수정 문구' })
  usePosterStore.getState().undo()
  assert.equal(usePosterStore.getState().poster.components[0].content, '찾습니다')
  usePosterStore.getState().redo()
  assert.equal(usePosterStore.getState().poster.components[0].content, '수정 문구')
})
