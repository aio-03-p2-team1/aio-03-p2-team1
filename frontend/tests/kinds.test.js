import assert from 'node:assert/strict'
import { loadKinds, withSpecies } from '../src/lib/kinds.js'

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
