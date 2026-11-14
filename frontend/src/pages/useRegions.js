import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

let cache = null

export function useRegions() {
  const [state, setState] = useState(cache || { list: [], source: null, error: null })
  useEffect(() => {
    if (cache) return
    api('/regions', { auth: false })
      .then((body) => {
        cache = { list: body.regions, source: body.data_source, error: null }
        setState(cache)
      })
      .catch((error) => setState({ list: [], source: null, error }))
  }, [])
  return state
}
