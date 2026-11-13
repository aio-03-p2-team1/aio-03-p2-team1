import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

let cache = null

/** /regions 시도 목록(공식 코드). 한 번 받아 재사용한다. */
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
