import { create } from 'zustand'

const copy = (value) => structuredClone(value)
const initialPast = []
const initialFuture = []

export const usePosterStore = create((set, get) => ({
  poster: null,
  selectedId: null,
  zoom: 0.62,
  past: initialPast,
  future: initialFuture,
  setPoster(poster) { set({ poster: copy(poster), selectedId: null, past: [], future: [] }) },
  select(selectedId) { set({ selectedId }) },
  setZoom(zoom) { set({ zoom }) },
  updateComponent(id, patch) {
    const { poster, past } = get()
    if (!poster) return
    set({ poster: { ...poster, components: poster.components.map((item) => item.id === id ? { ...item, ...patch } : item) }, past: [...past.slice(-39), copy(poster)], future: [] })
  },
  addComponent(component) {
    const { poster, past } = get()
    if (!poster) return
    set({ poster: { ...poster, components: [...poster.components, component] }, selectedId: component.id, past: [...past.slice(-39), copy(poster)], future: [] })
  },
  removeComponent(id) {
    const { poster, past } = get()
    if (!poster) return
    set({ poster: { ...poster, components: poster.components.filter((item) => item.id !== id) }, selectedId: null, past: [...past.slice(-39), copy(poster)], future: [] })
  },
  reorder(id, direction) {
    const { poster, past } = get()
    if (!poster) return
    const background = poster.components.filter((item) => item.type === 'background')
    const ordered = poster.components.filter((item) => item.type !== 'background').sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0))
    const index = ordered.findIndex((item) => item.id === id)
    const next = index + direction
    if (index < 0 || next < 0 || next >= ordered.length) return
    ;[ordered[index], ordered[next]] = [ordered[next], ordered[index]]
    set({ poster: { ...poster, components: [...background, ...ordered.map((item, zIndex) => ({ ...item, zIndex }))] }, past: [...past.slice(-39), copy(poster)], future: [] })
  },
  undo() {
    const { poster, past, future } = get()
    if (!past.length) return
    const previous = past[past.length - 1]
    set({ poster: previous, past: past.slice(0, -1), future: [copy(poster), ...future].slice(0, 40) })
  },
  redo() {
    const { poster, past, future } = get()
    if (!future.length) return
    set({ poster: future[0], past: [...past, copy(poster)].slice(-40), future: future.slice(1) })
  }
}))
