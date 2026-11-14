
export const SPECIES_OPTIONS = [
  { value: 'dog', label: '개' },
  { value: 'cat', label: '고양이' },
  { value: 'etc', label: '기타' },
  { value: 'all', label: '전체' }
]

export function speciesLabel(value) {
  return SPECIES_OPTIONS.find((o) => o.value === value)?.label ?? '미확인'
}

export function sexLabel(code) {
  return { M: '수컷', F: '암컷', Q: '미상' }[code] ?? '미확인'
}

export function neuterLabel(code) {
  return { Y: '예', N: '아니오', U: '미상' }[code] ?? '미확인'
}

export function formatDate(value) {
  if (!value) return '미확인'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  return m ? `${m[1]}.${m[2]}.${m[3]}` : String(value)
}

export function formatDateTime(value) {
  if (!value) return '미확인'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function sourceLabel(source) {
  return source === 'api' ? '실제 공고 데이터' : source === 'sample' ? '샘플 데이터' : '출처 미확인'
}

export function noticeTitle(item) {
  return item?.breed || item?.kind_name || '보호 동물 공고'
}

export function scopeText(scope) {
  if (!scope) return ''
  const region = !scope.region || scope.region === 'all' ? '전체 지역' : scope.region
  const period = `${formatDate(scope.start_date)}~${formatDate(scope.end_date)}`
  const base = `${region} · ${speciesLabel(scope.species)} · ${period}`
  if (scope.complete === false) {
    return `${base} · 전체 ${scope.total_count ?? 0}건 중 ${scope.fetched_rows ?? 0}건만 조회했어요`
  }
  return `${base} · 공고 ${scope.total_count ?? 0}건 확인`
}

export function telHref(tel) {
  if (!tel) return null
  const digits = String(tel).replace(/[^0-9+]/g, '')
  return digits.length >= 7 ? `tel:${digits}` : null
}

export function kakaoSearchUrl(address) {
  return address ? `https://map.kakao.com/link/search/${encodeURIComponent(address)}` : null
}

const ERROR_TEXT = {
  not_authenticated: '로그인이 필요해요.',
  auth_unavailable: '로그인 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.',
  origin_not_allowed: '허용되지 않은 주소에서 요청했어요. 관리자에게 CORS 설정을 확인해 달라고 알려 주세요.',
  network: '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.',
  notice_not_cached: '공고 정보를 다시 불러와야 해요. 목록에서 공고를 다시 선택해 주세요.',
  animal_auth: '구조동물 API 인증에 실패했어요(서버 키 확인 필요).',
  animal_rate_limit: '구조동물 API 호출 한도를 넘었어요. 잠시 후 다시 시도해 주세요.',
  animal_timeout: '구조동물 API 응답이 늦어요. 다시 시도해 주세요.'
}

export function errorMessage(error) {
  if (!error) return ''
  return error.message || ERROR_TEXT[error.code] || '요청을 처리하지 못했어요.'
}

export const LOCATION_REASON = {
  sample: '샘플 공고라 위치를 표시하지 않아요.',
  address_missing: '보호센터 주소가 공고에 없어요.',
  not_configured: '지도 기능이 아직 설정되지 않았어요.',
  address_not_found: '주소로 위치를 찾지 못했어요.',
  address_ambiguous: '주소에 해당하는 위치가 여러 곳이라 표시하지 않았어요.',
  invalid_coordinates: '좌표가 올바르지 않아 표시하지 않았어요.'
}

export const RUN_STATUS_LABEL = { completed: '완료', partial: '부분 결과', failed: '실패', awaiting_input: '추가 정보 필요', running: '진행 중' }

export function runStatusLabel(status) {
  return RUN_STATUS_LABEL[status] || '상태 미확인'
}

export function runSummary(criteria) {
  const c = criteria || {}
  const species = c.species ? speciesLabel(c.species).replace(/^개$/, '강아지') : '종류 미입력'
  const region = !c.region ? '지역 미입력' : c.region === 'all' ? '전체 지역' : c.region_name || c.region
  const since = c.start_date ? `${formatDate(c.start_date)}부터` : '기간 미입력'
  return `${species} · ${region} · ${since}`
}

export function paginate(items, page, size) {
  const list = Array.isArray(items) ? items : []
  const pages = Math.max(1, Math.ceil(list.length / size))
  const current = Math.min(Math.max(1, Math.floor(Number(page) || 1)), pages)
  return { items: list.slice((current - 1) * size, current * size), page: current, pages }
}
