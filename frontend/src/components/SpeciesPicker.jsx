const OPTIONS = [
  { value: 'dog', label: '강아지' },
  { value: 'cat', label: '고양이' },
  { value: 'etc', label: '기타 동물' },
  { value: 'all', label: '전체' }
]

function PawIcon() {
  return (
    <svg className="species-paw" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <ellipse cx="6.2" cy="10.2" rx="2.1" ry="2.6" />
      <ellipse cx="10.4" cy="6.4" rx="2.1" ry="2.7" />
      <ellipse cx="15.4" cy="7.4" rx="2" ry="2.6" />
      <path d="M11.6 11.6c-2.9 0-5.4 3.7-5.4 6.1 0 1.7 1.3 2.6 3 2.6 1.1 0 1.6-.6 2.6-.6s1.6.6 2.7.6c1.6 0 2.8-.9 2.8-2.5 0-2.5-2.7-6.2-5.7-6.2Z" />
    </svg>
  )
}

/** 동물 종류 선택 버튼(라디오 그룹). */
export default function SpeciesPicker({ value, onChange }) {
  return (
    <div className="species-picker" role="radiogroup" aria-label="동물 종류">
      {OPTIONS.map((o) => {
        const selected = value === o.value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`species-option${selected ? ' selected' : ''}`}
            onClick={() => onChange(o.value)}
          >
            <PawIcon />
            <span>{o.label}</span>
            {selected && <span className="species-check" aria-hidden="true">✓</span>}
          </button>
        )
      })}
    </div>
  )
}
