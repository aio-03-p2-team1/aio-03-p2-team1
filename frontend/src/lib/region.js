
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

export function matchRegion(sido, regions) {
  if (!sido) return null
  const exact = regions.find((r) => r.name === sido)
  if (exact) return exact.name
  const short = shortRegion(sido)
  return regions.find((r) => shortRegion(r.name) === short)?.name ?? null
}
