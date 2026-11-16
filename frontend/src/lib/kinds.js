import { api } from './api.js'

const cache = new Map()
export function loadKinds(species, fetcher = api) {
  const cached = cache.get(species)
  if (cached && cached.expires > Date.now()) return cached.promise
  const promise = fetcher(`/kinds?species=${encodeURIComponent(species)}`)
    .then((body) => body.kinds)
    .catch((error) => { cache.delete(species); throw error })
  cache.set(species, { promise, expires: Date.now() + 86400000 })
  return promise
}

export function withSpecies(form, species) {
  const { breed, ...rest } = form
  return { ...rest, species, breed_code: form.species === species ? (form.breed_code || '') : '' }
}

export function withPhotoBreed(form, result) {
  const next = withSpecies(form, result.species || form.species)
  return { ...next, breed_code: next.breed_code || result.breed_code || '' }
}

export function breedRequest(form) {
  return { breed_code: form.breed_code || '' }
}
