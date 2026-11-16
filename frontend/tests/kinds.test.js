import assert from 'node:assert/strict'
import { loadKinds, withSpecies, withPhotoBreed } from '../src/lib/kinds.js'

let calls = 0
const fetcher = async () => { calls++; return { kinds: [{ name: '푸들' }] } }
await Promise.all([loadKinds('dog', fetcher), loadKinds('dog', fetcher)])
await loadKinds('cat', fetcher)
await loadKinds('dog', fetcher)
assert.equal(calls, 2)
let attempts = 0
const failing = async () => { attempts++; throw new Error('unavailable') }
await assert.rejects(loadKinds('etc', failing))
await assert.rejects(loadKinds('etc', failing))
assert.equal(attempts, 2)

// Photo-driven automatic resubmission must never carry a dog breed into cat search.
const photoSearch = withSpecies({ species: 'dog', breed: '푸들', description: '사진 특징' }, 'cat')
assert.equal(photoSearch.breed, '')
assert.equal(photoSearch.description, '사진 특징')
assert.equal(withSpecies({ species: 'dog', breed: '푸들' }, 'dog').breed, '푸들')
assert.equal(withSpecies({ species: 'dog', breed: '푸들' }, '').breed, '')

assert.equal(withPhotoBreed({ species: 'dog', breed: '' }, { species: 'dog', breed_code: '1', breed: '푸들' }).breed, '푸들')
assert.equal(withPhotoBreed({ species: 'dog', breed: '푸들' }, { species: 'cat', breed_code: '2', breed: '코리안 숏헤어' }).breed, '코리안 숏헤어')
assert.equal(withPhotoBreed({ species: 'dog', breed: '' }, { species: 'dog', breed_code: '', breed: '임의 품종' }).breed, '')
