// 검색 에이전트의 입력 검토 결과(run.input_review)를 화면에 보여 줄 줄로 바꾼다.
// 판단 문장·합친 중복·글과 사진이 어긋난 항목·다음 행동을 짧게 정리한다.
export function inputReviewView(review, currentText = '') {
  if (!review || !review.message) return null
  const lines = [...(review.filters || [])]
  if (review.duplicates?.length) lines.push(`합친 중복: ${review.duplicates.join(', ')}`)
  for (const c of review.conflicts || []) {
    lines.push(`어긋난 정보: ${c.item} — 글 ${c.text_value || '없음'} / 사진 ${c.photo_value || '없음'} (글 기준으로 찾아요)`)
  }
  const organized = (review.organized_text || '').trim()
  return {
    title: review.action === 'ask' ? '에이전트가 먼저 확인할게요' : '에이전트가 입력을 정리했어요',
    message: review.message,
    question: review.action === 'ask' ? review.question || '' : '',
    lines,
    organized,
    canApply: Boolean(organized) && organized !== String(currentText || '').trim(),
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
