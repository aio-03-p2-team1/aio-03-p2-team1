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
  return { ...form, species, breed: form.species === species ? (form.breed || '') : '' }
}

export function withPhotoBreed(form, result) {
  const next = result.species ? withSpecies(form, result.species) : { ...form }
  return { ...next, breed: next.breed || (result.breed_code ? result.breed : '') || '' }
}
