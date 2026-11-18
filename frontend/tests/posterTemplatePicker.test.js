import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LEGACY_TEMPLATE_LABEL, nextTemplateIndex, templateOptions } from '../src/lib/posterTemplatePicker.js'

const templates = [
  { id: 'lost-a4', name: '일반형', description: '794 × 1123', width: 794 },
  { id: 'lost-shorts', name: '긴급형', description: '720 × 1280' },
]

test('template options keep id, name and size description in server order', () => {
  assert.deepEqual(templateOptions(templates, 'lost-a4'), [
    { id: 'lost-a4', name: '일반형', description: '794 × 1123' },
    { id: 'lost-shorts', name: '긴급형', description: '720 × 1280' },
  ])
})

test('a poster made from a template that is no longer listed shows a legacy option first', () => {
  const options = templateOptions(templates, 'old-template')
  assert.equal(options.length, 3)
  assert.deepEqual(options[0], { id: 'old-template', name: LEGACY_TEMPLATE_LABEL, description: '', legacy: true })
  assert.deepEqual(templateOptions([], undefined), [])
})

test('keyboard navigation stops at both ends and supports Home/End', () => {
  assert.equal(nextTemplateIndex(0, 'ArrowDown', 3), 1)
  assert.equal(nextTemplateIndex(2, 'ArrowDown', 3), 2)
  assert.equal(nextTemplateIndex(0, 'ArrowUp', 3), 0)
  assert.equal(nextTemplateIndex(1, 'Home', 3), 0)
  assert.equal(nextTemplateIndex(0, 'End', 3), 2)
  assert.equal(nextTemplateIndex(-1, 'ArrowDown', 3), 1)
  assert.equal(nextTemplateIndex(0, 'ArrowDown', 0), -1)
})
