import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'

const SearchViewContext = createContext(null)

// Routes 바깥에 두어 상세 페이지 방문 시에도 유지한다. 계정 변경 시 provider key로 초기화한다.
export function SearchViewProvider({ children }) {
  const [view, setView] = useState({})
  const scrolls = useRef(new Map())
  useEffect(() => {
    const photo = view.photo
    if (photo) return () => URL.revokeObjectURL(photo)
  }, [view.photo])
  return <SearchViewContext.Provider value={{ view, setView, scrolls }}>{children}</SearchViewContext.Provider>
}

export function useSearchScroll(key, ready) {
  const { scrolls } = useContext(SearchViewContext)
  useLayoutEffect(() => {
    if (!ready) return
    const frame = requestAnimationFrame(() => window.scrollTo(0, scrolls.current.get(key) || 0))
    return () => {
      cancelAnimationFrame(frame)
      scrolls.current.set(key, window.scrollY)
      if (scrolls.current.size > 45) scrolls.current.delete(scrolls.current.keys().next().value)
    }
  }, [key, ready, scrolls])
}

export function useSearchViewState(key, initial) {
  const { view, setView } = useContext(SearchViewContext)
  const [fallback] = useState(initial)
  const set = useCallback((next) => setView((previous) => ({
    ...previous,
    [key]: typeof next === 'function' ? next(previous[key] ?? fallback) : next,
  })), [key, setView, fallback])
  return [view[key] ?? fallback, set]
}
