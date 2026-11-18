import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPosterFromTemplate, POSTER_FIELDS, posterPayload, switchPosterTemplate } from '../src/lib/posterDocument.js'

const basic = {
  id: 'basic', width: 794, height: 1123,
  components: [
    { id: 'title', type: 'text', fieldKey: 'title', content: '강아지를 찾습니다', x: 1, y: 2, width: 600, height: 60 },
    { id: 'photo', type: 'image', assetId: null, x: 100, y: 140, width: 560, height: 440 }
  ]
}
const ids = () => {
  let next = 0
  return () => `generated-${++next}`
}

test('template document provides all standard text fields on the A4 canvas', () => {
  const doc = createPosterFromTemplate(basic, ids())
  assert.deepEqual([doc.width, doc.height, doc.templateId], [794, 1123, 'basic'])
  assert.deepEqual(
    doc.components.filter((item) => item.type === 'text').map((item) => item.fieldKey).sort(),
    POSTER_FIELDS.map(([key]) => key).sort()
  )
  assert.equal(new Set(doc.components.map((item) => item.id)).size, doc.components.length)
})

test('template switch keeps field values and every uploaded photo while resetting placement', () => {
  const previous = {
    ...createPosterFromTemplate(basic, ids()),
    components: [
      { id: 'title', type: 'text', fieldKey: 'title', content: '보리를 찾아요', x: 320, y: 20, width: 200, height: 50 },
      { id: 'pet', type: 'text', fieldKey: 'pet_name', content: '보리', x: 200, y: 160, width: 200, height: 40 },
      { id: 'one', type: 'image', assetId: 'asset-one', x: 20, y: 20, width: 120, height: 100, cropZoom: 1.4 },
      { id: 'two', type: 'image', assetId: 'asset-two', x: 600, y: 700, width: 120, height: 100, cropX: 0.8 }
    ]
  }
  const info = { id: 'info', width: 794, height: 1123, components: [
    { id: 'title', type: 'text', fieldKey: 'title', content: '기본 제목', x: 0, y: 0, width: 1, height: 1 },
    { id: 'photo', type: 'image', assetId: null, x: 92, y: 140, width: 610, height: 430 },
    { id: 'pet', type: 'text', fieldKey: 'pet_name', content: '이름', x: 0, y: 0, width: 1, height: 1 }
  ] }
  const next = switchPosterTemplate(previous, info, ids())
  const byKey = Object.fromEntries(next.components.filter((item) => item.fieldKey).map((item) => [item.fieldKey, item]))
  const photos = next.components.filter((item) => item.type === 'image' && item.assetId)
  assert.equal(byKey.title.content, '보리를 찾아요')
  assert.equal(byKey.pet_name.content, '보리')
  assert.equal(byKey.title.y, 0)
  assert.equal(byKey.title.width, 1)
  assert.deepEqual(photos.map((item) => item.assetId), ['asset-one', 'asset-two'])
  assert.equal(photos[0].cropZoom, 1.4)
  assert.equal(photos[1].cropX, 0.8)
  assert.equal(photos[0].y, photos[1].y)
  assert.ok(photos[1].x > photos[0].x)
  assert.equal(new Set(next.components.map((item) => item.id)).size, next.components.length)
})


test('server template geometry and typography survive document creation', () => {
  const template = structuredClone(basic)
  Object.assign(template.components[0], { x: 64, y: 38, width: 682, height: 78, fontSize: 46, align: 'left', color: '#163E32' })
  const doc = createPosterFromTemplate(template, ids())
  const title = doc.components.find((item) => item.fieldKey === 'title')
  for (const key of ['x', 'y', 'width', 'height', 'fontSize', 'align', 'color']) {
    assert.equal(title[key], template.components[0][key])
  }
  assert.equal(template.components.length, 2)
})

test('save payload drops id and other extra keys from a loaded poster', () => {
  const loaded = { id: 'a'.repeat(32), templateId: 'basic', width: 794, height: 1123, components: [{ id: 'x' }], extra: 1 }
  assert.deepEqual(posterPayload(loaded), { templateId: 'basic', width: 794, height: 1123, components: [{ id: 'x' }] })
})
