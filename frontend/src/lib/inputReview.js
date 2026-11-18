// 검색 에이전트의 입력 검토 결과(run.input_review)를 화면에 보여 줄 줄로 바꾼다.
// 판단 문장·거른 조건·합친 중복·글과 사진이 어긋난 항목을 짧게 정리한다(정리한 글은 입력란에 바로 반영).
export function inputReviewView(review) {
  if (!review || !review.message) return null
  const lines = [...(review.filters || [])]
  if (review.duplicates?.length) lines.push(`합친 중복: ${review.duplicates.join(', ')}`)
  for (const c of review.conflicts || []) {
    lines.push(`어긋난 정보: ${c.item} — 글 ${c.text_value || '없음'} / 사진 ${c.photo_value || '없음'} (글 기준으로 찾아요)`)
  }
  if ((review.organized_text || '').trim()) lines.push('특징과 상황을 정리한 글로 바꿨어요.')
  return {
    title: review.action === 'ask' ? '에이전트가 먼저 확인할게요' : '에이전트가 입력을 정리했어요',
    message: review.message,
    question: review.action === 'ask' ? review.question || '' : '',
    lines,
  }
}

// 기타 동물 종류 거르기 요약(run.kind_check)을 한 줄로 보여 준다. 글·사진으로 확인한 공고만 남긴다.
export function kindCheckText(check) {
  if (!check || !check.target) return ''
  const parts = [`${check.target}로 확인된 공고 ${check.kept}건`]
  if (check.kept) parts.push(`글 ${check.kept_by_text}건 · 사진 ${check.kept_by_photo}건`)
  const dropped = []
  if (check.other_kind) dropped.push(`다른 동물 ${check.other_kind}건`)
  if (check.unknown) dropped.push(`종류를 확인하지 못한 ${check.unknown}건`)
  return `기타 동물 ${check.checked}건 중 ${parts.join(' (')}${check.kept ? ')' : ''}${dropped.length ? ` · 제외: ${dropped.join(', ')}` : ''}`
}

// 입력 검토가 물은 글·사진 모순에 사용자가 사진 값을 고르면 정리한 글의 그 항목 줄을 사진 값으로 바꾼다.
// 같은 항목 줄([털색]: …)이 없으면 아래에 새 줄로 덧붙인다(덧붙여서 같은 항목이 두 번 적히지 않게).
export function applyPhotoValue(text, conflict) {
  const item = String(conflict?.item || '').trim()
  const value = String(conflict?.photo_value || '').trim()
  if (!item || !value) return text
  const line = `[${item}]: ${value}`
  const lines = String(text || '').split('\n')
  const at = lines.findIndex((l) => l.trimStart().startsWith(`[${item}]`))
  if (at >= 0) {
    lines[at] = line
    return lines.join('\n')
  }
  return [String(text || '').trimEnd(), line].filter(Boolean).join('\n')
}
