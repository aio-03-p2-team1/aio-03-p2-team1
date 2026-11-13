export function pageNumber(value) {
  const page = Number(value)
  return Number.isSafeInteger(page) && page > 0 ? page : 1
}

export function cachedPage(cache, key, now = Date.now()) {
  const entry = cache[key]
  return entry && entry.expiresAt > now ? entry.value : null
}

export function rememberPage(cache, key, value, now = Date.now()) {
  const entries = Object.entries(cache).filter(([k, v]) => k !== key && v.expiresAt > now).slice(-44)
  return { ...Object.fromEntries(entries), [key]: { value, expiresAt: now + 600000 } }
}
