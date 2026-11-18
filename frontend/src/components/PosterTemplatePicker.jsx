import { useEffect, useId, useRef, useState } from 'react'
import { posterBackgroundUrl } from './PosterCanvasItem.jsx'
import { nextTemplateIndex, templateOptions } from '../lib/posterTemplatePicker.js'

// 템플릿 드롭다운: 기본 <select> 는 이미지를 넣을 수 없어서 버튼 + 목록(listbox)으로 만든다.
// 각 항목에 템플릿 배경 미리보기 이미지와 이름·크기를 함께 보여 준다.

function Thumb({ id }) {
  const src = posterBackgroundUrl(id)
  return <span className="poster-template-thumb" aria-hidden="true">
    {src ? <img src={src} alt="" loading="lazy" decoding="async" /> : <span className="poster-template-thumb-empty">?</span>}
  </span>
}

export default function PosterTemplatePicker({ templates, value, onChange, disabled = false }) {
  const options = templateOptions(templates, value)
  const selected = options.find((item) => item.id === value) || options[0]
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const rootRef = useRef(null)
  const listRef = useRef(null)
  const buttonRef = useRef(null)
  const listId = useId()

  useEffect(() => {
    if (!open) return
    listRef.current?.focus()
    const close = (event) => { if (!rootRef.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  function toggle() {
    if (disabled) return
    setActive(Math.max(0, options.findIndex((item) => item.id === value)))
    setOpen((current) => !current)
  }

  function choose(item) {
    setOpen(false)
    buttonRef.current?.focus()
    if (item && item.id !== value) onChange(item.id)
  }

  function onListKeyDown(event) {
    if (event.key === 'Escape' || event.key === 'Tab') {
      setOpen(false)
      if (event.key === 'Escape') { event.preventDefault(); buttonRef.current?.focus() }
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      choose(options[active])
      return
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      setActive((index) => nextTemplateIndex(index, event.key, options.length))
    }
  }

  return <div className="poster-template-picker" ref={rootRef}>
    <span className="poster-template-label" id={`${listId}-label`}>템플릿</span>
    <button ref={buttonRef} type="button" className="poster-template-button" disabled={disabled}
      aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} aria-labelledby={`${listId}-label ${listId}-value`}
      onClick={toggle}
      onKeyDown={(event) => { if (event.key === 'ArrowDown' && !open) { event.preventDefault(); toggle() } }}>
      {selected && <Thumb id={selected.id} />}
      <span className="poster-template-text" id={`${listId}-value`}>
        <strong>{selected?.name || '템플릿 없음'}</strong>
        {selected?.description && <small>{selected.description}</small>}
      </span>
      <span className="poster-template-caret" aria-hidden="true">▾</span>
    </button>
    {open && <ul ref={listRef} id={listId} className="poster-template-list" role="listbox" tabIndex={-1}
      aria-labelledby={`${listId}-label`} aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
      onKeyDown={onListKeyDown}>
      {options.map((item, index) => <li key={item.id} id={`${listId}-${index}`} role="option" aria-selected={item.id === value}
        className={`poster-template-option${index === active ? ' active' : ''}${item.id === value ? ' selected' : ''}`}
        onPointerEnter={() => setActive(index)} onClick={() => choose(item)}>
        <Thumb id={item.id} />
        <span className="poster-template-text"><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</span>
        {item.id === value && <span className="poster-template-check" aria-hidden="true">✓</span>}
      </li>)}
    </ul>}
  </div>
}
