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
