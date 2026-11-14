// 검색 반경 표시용 순수 함수. node --test 로 시험한다(tests/radius.test.js).
// 반경 값·중심 좌표는 서버가 계산한 값(run.radius)만 쓴다. 브라우저에서 따로 계산하지 않는다.

export const RADIUS_STEPS_KM = [3, 10, 20, null]

export function kmLabel(km) {
  if (km == null) return '조회 지역 전체'
  return `반경 ${Number.isInteger(km) ? km : km.toFixed(1)}km`
}

/** 결과 위에 보여 줄 한 줄 요약. 반경을 쓰지 않았으면 그 이유를 알려 준다. */
export function radiusText(radius) {
  if (!radius) return ''
  if (!radius.applied) {
    if (radius.reason === 'whole_region') return '실종 후 2주가 지나 조회 지역 전체에서 찾았어요.'
    return radius.reason_text ? `${radius.reason_text}.` : '반경을 적용하지 않았어요.'
  }
  const parts = [`실종 위치에서 직선거리 ${kmLabel(radius.radius_km).replace('반경 ', '')} 안`]
  parts.push(`${radius.inside ?? 0}건`)
  if (radius.unknown) parts.push(`거리 미확인 ${radius.unknown}건 포함`)
  if (radius.excluded) parts.push(`반경 밖 ${radius.excluded}건 제외`)
  return `${parts.join(' · ')} (관할 구청 기준 직선거리, 도로 거리 아님)`
}

/** 이전 단계 반경(km). 넓힌 경우 지도에 점선 원으로 함께 보여 준다. */
export function previousRadiusKm(radius) {
  if (!radius?.applied || !(radius.step > 0)) return null
  return RADIUS_STEPS_KM[radius.step - 1] ?? null
}

/** 공고 카드에 붙일 거리 문구. */
export function distanceLabel(candidate) {
  if (!candidate || candidate.distance_basis == null) return ''
  if (candidate.distance_km == null) return '거리 미확인'
  return `약 ${candidate.distance_km}km(관할 기준)`
}

/** 반경 넓히기 질문(field=radius)에서 다음 단계와 버튼 문구를 꺼낸다. */
export function widenRadiusAction(questions, radius) {
  const q = (questions || []).find((item) => item.field === 'radius')
  if (!q || !Number.isInteger(q.next_step)) return null
  const km = RADIUS_STEPS_KM[q.next_step]
  return { step: q.next_step, label: `${kmLabel(km)}로 넓혀 찾기`, from: radius?.radius_km ?? null }
}
