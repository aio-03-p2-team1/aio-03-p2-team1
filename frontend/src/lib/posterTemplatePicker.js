// 전단지 템플릿 선택 목록(이미지 + 이름 드롭다운)의 화면 밖 로직.

export const LEGACY_TEMPLATE_LABEL = '기존 전단지'

// 목록에 없는 템플릿으로 만든 전단지(예전 템플릿)는 맨 앞에 '기존 전단지' 항목을 둔다.
export function templateOptions(templates, currentId) {
  const items = (templates || []).map((item) => ({ id: item.id, name: item.name, description: item.description || '' }))
  if (currentId && !items.some((item) => item.id === currentId)) {
    items.unshift({ id: currentId, name: LEGACY_TEMPLATE_LABEL, description: '', legacy: true })
  }
  return items
}

// 키보드로 목록을 움직인다. 처음·끝에서 멈추고(돌지 않음) Home/End 로 양 끝에 간다.
export function nextTemplateIndex(index, key, length) {
  if (length <= 0) return -1
  const current = index < 0 ? 0 : Math.min(index, length - 1)
  if (key === 'ArrowDown') return Math.min(current + 1, length - 1)
  if (key === 'ArrowUp') return Math.max(current - 1, 0)
  if (key === 'Home') return 0
  if (key === 'End') return length - 1
  return current
}
