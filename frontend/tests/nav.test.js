import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldReloadOnNav } from '../src/lib/nav.js'

test('clicking the menu of the current page reloads it', () => {
  assert.equal(shouldReloadOnNav('/search', '/search', { button: 0 }), true)
  assert.equal(shouldReloadOnNav('/', '/', { button: 0 }), true)
  assert.equal(shouldReloadOnNav('/board/', '/board', { button: 0 }), true)
})

test('clicking a different page keeps in-app navigation', () => {
  assert.equal(shouldReloadOnNav('/board', '/search', { button: 0 }), false)
  assert.equal(shouldReloadOnNav('/board/abc', '/board', { button: 0 }), false)
  assert.equal(shouldReloadOnNav('/notices/1', '/', { button: 0 }), false)
})

test('new-tab clicks and other buttons are left to the browser', () => {
  for (const key of ['metaKey', 'ctrlKey', 'shiftKey', 'altKey']) {
    assert.equal(shouldReloadOnNav('/search', '/search', { button: 0, [key]: true }), false)
  }
  assert.equal(shouldReloadOnNav('/search', '/search', { button: 1 }), false)
  assert.equal(shouldReloadOnNav('/search', '/search', { button: 0, defaultPrevented: true }), false)
})
