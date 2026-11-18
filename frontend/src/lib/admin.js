// 관리자 화면에서 쓰는 표시·내보내기 함수(화면과 분리해 node --test 로 시험한다).

export const ADMIN_TABS = [
  { id: 'overview', label: '현황' },
  { id: 'agent', label: '에이전트 분석' },
  { id: 'runs', label: '실행 내역' },
  { id: 'users', label: '사용자' },
  { id: 'posts', label: '게시물' },
  { id: 'comments', label: '댓글' },
  { id: 'posters', label: '전단지' },
  { id: 'logs', label: '로그' },
]

export function tabFromSearch(search) {
  const id = new URLSearchParams(search || '').get('tab')
  return ADMIN_TABS.some((t) => t.id === id) ? id : 'overview'
}

// 집계 이름 → 화면 이름. 없는 이름은 원래 코드 그대로 보여 준다(감추지 않는다).
export const STAT_LABELS = {
  few_features: '입력 특징 1개 이하',
  mixed_breed: '믹스견·사진 없음',
  weak_similarity: '1등 유사도 낮음',
  flat_top: '1·2등 차이 작음',
  no_feature_match: '1등 일치 근거 없음',
  arg_mapping: '지역 매핑 실패',
  duplicates: '중복 공고',
  condition_violation: '조건 위반',
  empty_narrow: '결과 0건',
  empty_radius: '반경 안 0건',
  tool_error: '도구 오류',
  field_missing: '필드 누락',
  llm: 'LLM 판단',
  no_llm: 'LLM 없음',
  llm_error: 'LLM 오류',
  step_limit: '걸음 한도',
  no_tool_call: '도구 미선택',
  photo: '사진 요청',
  info: '정보 요청',
}

export function statLabel(key) {
  return STAT_LABELS[key] || key || '-'
}

/** {이름: 수} → 많은 순 [{key, label, count, share}] */
export function counterRows(counter) {
  const entries = Object.entries(counter || {}).filter(([, v]) => Number.isFinite(v))
  const total = entries.reduce((sum, [, v]) => sum + v, 0)
  return entries
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .map(([key, count]) => ({ key, label: statLabel(key), count, share: total ? count / total : 0 }))
}

export function percent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 1000) / 10}%` : '미측정'
}

export function number(value, unit = '') {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString('ko-KR')}${unit}` : '미측정'
}

function csvCell(value) {
  const text = value === null || value === undefined ? '' : Array.isArray(value) ? value.join('|') : String(value)
  // 스프레드시트가 수식으로 실행하지 않도록 =,+,-,@ 로 시작하는 값 앞에 ' 를 붙인다.
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

export const RUN_CSV_COLUMNS = [
  'created_at', 'email', 'status', 'end_reason', 'reflection_enabled', 'reflection_count', 'retry_count', 'tool_call_count',
  'cache_hit', 'elapsed_ms', 'confidence_low', 'confidence_reasons', 'agent_source', 'agent_final_tool', 'agent_steps',
  'agent_reruns', 'agent_request', 'issues', 'error', 'ranking_method', 'radius_km', 'data_source', 'id',
]

/** 실행 내역 → CSV(정확도 개선 데이터 내려받기). 첫 줄은 열 이름. */
export function runsToCsv(rows, columns = RUN_CSV_COLUMNS) {
  const lines = [columns.join(',')]
  for (const row of rows || []) lines.push(columns.map((c) => csvCell(row[c])).join(','))
  return lines.join('\n')
}

export function downloadText(filename, text, type = 'text/plain') {
  const blob = new Blob([text], { type: `${type};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
