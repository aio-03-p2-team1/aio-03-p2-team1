// 에이전트 요청 카드(사진·추가 정보) 화면 로직.
// 서버의 assess 노드가 결과가 애매하다고 판단하면 run.agent_request 를 보낸다.
//   { type: 'photo', reason }  또는  { type: 'info', field, label, options, reason }
// 사용자가 고른 답은 설명 글을 몰래 고치지 않고 '답한 값' 칩으로 따로 보여 주고, 검색 조건에 합쳐 보낸다.

export const FIELD_LABELS = { color: '털색', size: '크기', sex: '성별', marks: '특징' }

// 지금 보여 줄 요청. '잘 모르겠어요'한 항목이나 이미 답한 항목이면 숨긴다.
export function visibleRequest(run, answers = {}, declined = []) {
  const request = run?.agent_request
  if (!request || run.status === 'awaiting_input') return null
  const key = request.type === 'photo' ? 'photo' : request.field
  if (declined.includes(key)) return null
  if (request.type === 'info' && answers[request.field]?.length) return null
  return request
}

// 답한 값을 칩으로. marks 는 여러 개를 고를 수 있다.
export function answerChips(answers = {}) {
  return Object.entries(answers).flatMap(([field, values]) =>
    (values || []).map((value) => ({ field, value, label: `${FIELD_LABELS[field] || field}: ${value}` })))
}

export function addAnswer(answers, field, value) {
  const current = answers[field] || []
  if (current.includes(value)) return answers
  // 털색·특징은 여러 개, 크기·성별은 하나만.
  const next = field === 'color' || field === 'marks' ? [...current, value] : [value]
  return { ...answers, [field]: next }
}

export function removeAnswer(answers, field, value) {
  const rest = (answers[field] || []).filter((v) => v !== value)
  const next = { ...answers }
  if (rest.length) next[field] = rest
  else delete next[field]
  return next
}

// 답한 값을 검색 조건에 합친다. 서버가 아는 필드(color·size·sex)는 그 칸으로, 특징은 설명 끝에 덧붙인다.
export function applyAnswers(criteria, answers = {}) {
  const out = { ...criteria }
  if (answers.color?.length) out.color = answers.color.join(' ')
  if (answers.size?.length) out.size = answers.size[0]
  if (answers.sex?.length) out.sex = answers.sex[0] === '수컷' ? 'M' : answers.sex[0] === '암컷' ? 'F' : undefined
  if (out.sex === undefined) delete out.sex
  if (answers.marks?.length) {
    const extra = `추가 특징: ${answers.marks.join(', ')}`
    out.description = [out.description, extra].filter(Boolean).join('\n').slice(0, 1000)
  }
  return out
}
