import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'

const SearchViewContext = createContext(null)

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
    // 이 화면에서 저장해 둔 위치가 있을 때만(상세에서 돌아온 경우) 되돌린다.
    // 새 검색·새 페이지는 저장값이 없으니 맨 위로 보내지 않고, 검색 결과로 이동하는 쪽 동작을 그대로 둔다.
    const saved = scrolls.current.get(key)
    const frame = saved === undefined ? 0 : requestAnimationFrame(() => window.scrollTo(0, saved))
    return () => {
      if (frame) cancelAnimationFrame(frame)
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
