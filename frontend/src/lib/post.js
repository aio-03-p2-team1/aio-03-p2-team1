// 실종 정보 게시판 화면용 순수 함수. node --test 로 시험한다(tests/post.test.js).

export const POST_SPECIES = [
  { value: 'dog', label: '강아지' },
  { value: 'cat', label: '고양이' },
  { value: 'etc', label: '기타' }
]

export const MAX_PHOTO_BYTES = 400 * 1024
export const MAX_LOST_DAYS = 365

export function postSpeciesLabel(value) {
  return POST_SPECIES.find((o) => o.value === value)?.label ?? '미확인'
}

/** 로컬 날짜 'YYYY-MM-DD' (date input 값과 같은 형식). */
export function localDate(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function daysBetween(a, b) {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000)
}

/**
 * 등록 폼 검사. 서버도 같은 규칙으로 다시 검사한다(클라이언트 값을 믿지 않음).
 * 반환: { 필드이름: 메시지 } — 비어 있으면 통과.
 */
export function validatePost(form, today = localDate()) {
  const errors = {}
  const name = String(form.pet_name || '').trim()
  const description = String(form.description || '').trim()
  if (!name) errors.pet_name = '반려동물 이름을 적어 주세요.'
  else if (name.length > 20) errors.pet_name = '이름은 20자 이내로 적어 주세요.'
  if (!POST_SPECIES.some((o) => o.value === form.species)) errors.species = '동물 종류를 선택해 주세요.'
  const region = String(form.region || '').trim()
  if (!region || region === '전체') errors.region = '실종 위치를 지도에서 선택해 주세요.'
  if (String(form.lost_place || '').trim().length > 100) errors.region = '실종 위치 주소가 너무 길어요.'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.lost_date || '')) {
    errors.lost_date = '실종 날짜를 선택해 주세요.'
  } else if (form.lost_date > today) {
    errors.lost_date = '실종 날짜가 오늘 이후일 수 없어요.'
  } else if (daysBetween(form.lost_date, today) > MAX_LOST_DAYS) {
    errors.lost_date = '최근 1년 이내 날짜만 등록할 수 있어요.'
  }
  if (String(form.breed || '').trim().length > 30) errors.breed = '품종은 30자 이내로 적어 주세요.'
  if (description.length < 5) errors.description = '특징과 마지막으로 본 장소를 5자 이상 적어 주세요.'
  else if (description.length > 1000) errors.description = '1000자 이내로 적어 주세요.'
  return errors
}

/** data URL 의 실제 바이트 수(base64 길이로 계산). */
export function dataUrlBytes(dataUrl) {
  const comma = String(dataUrl || '').indexOf(',')
  if (comma < 0) return 0
  const b64 = dataUrl.slice(comma + 1).replace(/\s/g, '')
  const pad = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0
  return Math.floor((b64.length * 3) / 4) - pad
}

/** 게시글 사진 주소(API 가 이미지 바이트를 돌려준다). */
export function postPhotoPath(id) {
  return `/posts/${encodeURIComponent(id)}/photo`
}

/** 받침이 있으면 '을', 없으면 '를'. 한글이 아니면 '을(를)'. */
export function objectParticle(word) {
  const code = String(word || '').trim().slice(-1).charCodeAt(0)
  if (!(code >= 0xac00 && code <= 0xd7a3)) return '을(를)'
  return (code - 0xac00) % 28 ? '을' : '를'
}

export function postTitle(post) {
  const name = String(post?.pet_name || '').trim()
  return name ? `${name}${objectParticle(name)} 찾습니다` : '실종 정보'
}
