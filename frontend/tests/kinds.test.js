import assert from 'node:assert/strict'
import { loadKinds, withSpecies, withPhotoBreed, breedRequest } from '../src/lib/kinds.js'

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

// Manual selection and photo resubmission retain codes, never request names.
const photoSearch = withSpecies({ species: 'dog', breed_code: '1', description: '사진 특징' }, 'cat')
assert.equal(photoSearch.breed_code, '')
assert.equal(photoSearch.description, '사진 특징')
assert.equal(withSpecies({ species: 'dog', breed_code: '1' }, 'dog').breed_code, '1')
assert.equal(withSpecies({ species: 'dog', breed_code: '1' }, '').breed_code, '')
assert.equal(withPhotoBreed({ species: 'dog', breed_code: '' }, { species: 'dog', breed_code: '1', breed: '푸들' }).breed_code, '1')
assert.equal(withPhotoBreed({ species: 'dog', breed_code: '1' }, { species: 'cat', breed_code: '2', breed: '코리안 숏헤어' }).breed_code, '2')
assert.deepEqual(breedRequest({ breed_code: '1', breed: '푸들' }), { breed_code: '1' })
assert.deepEqual(breedRequest({}), { breed_code: '' })
assert.equal(withPhotoBreed({ species: 'dog', breed_code: '' }, { species: 'dog', breed_code: '', breed: '임의 품종' }).breed_code, '')
