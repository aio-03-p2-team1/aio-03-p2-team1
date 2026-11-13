// 카카오 주소의 시·도 이름을 구조동물 API 의 공식 시·도 이름(/regions)으로 맞춘다.
// 예: '서울' · '서울특별시' → '서울특별시', '강원특별자치도' · '강원' → '강원특별자치도'(목록에 있는 이름)

const SHORT = [
  ['서울', '서울'], ['부산', '부산'], ['대구', '대구'], ['인천', '인천'], ['광주', '광주'], ['대전', '대전'],
  ['울산', '울산'], ['세종', '세종'], ['경기', '경기'], ['강원', '강원'], ['충청북', '충북'], ['충북', '충북'],
  ['충청남', '충남'], ['충남', '충남'], ['전라북', '전북'], ['전북', '전북'], ['전라남', '전남'], ['전남', '전남'],
  ['경상북', '경북'], ['경북', '경북'], ['경상남', '경남'], ['경남', '경남'], ['제주', '제주']
]

export function shortRegion(name) {
  const value = String(name || '').trim()
  const hit = SHORT.find(([prefix]) => value.startsWith(prefix))
  return hit ? hit[1] : value
}

/** 시·도 이름을 공식 목록의 이름으로 바꾼다. 못 찾으면 null(임의 값으로 대체하지 않음). */
export function matchRegion(sido, regions) {
  if (!sido) return null
  const exact = regions.find((r) => r.name === sido)
  if (exact) return exact.name
  const short = shortRegion(sido)
  return regions.find((r) => shortRegion(r.name) === short)?.name ?? null
}
