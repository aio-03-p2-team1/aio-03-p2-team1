export default function Pagination({ page, pages, disabled, onChange }) {
  if (pages <= 1) return null
  const start = Math.max(1, Math.min(page - 2, pages - 4))
  return (
    <nav className="pagination" aria-label="검색 결과 페이지">
      <button type="button" disabled={disabled || page <= 1} onClick={() => onChange(page - 1)}>이전</button>
      {Array.from({ length: Math.min(5, pages) }, (_, index) => start + index).map((number) => (
        <button type="button" key={number} disabled={disabled} aria-current={number === page ? 'page' : undefined} onClick={() => onChange(number)}>{number}</button>
      ))}
      <button type="button" disabled={disabled || page >= pages} onClick={() => onChange(page + 1)}>다음</button>
      <span>{page} / {pages}</span>
    </nav>
  )
}
