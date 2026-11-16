// 검색 반경 표시용 순수 함수. node --test 로 시험한다(tests/radius.test.js).
// 검색 결과의 반경 값·중심 좌표는 서버가 계산한 값(run.radius)만 쓴다.
// 검색 전 미리 보기(previewRadius)만 브라우저에서 같은 기준표로 계산한다.

// 서버 backend/agent/radius.py 의 RADIUS_STEPS_KM·STEP_BY_DAYS 와 같아야 한다(값을 바꾸면 양쪽 모두 고친다).
export const RADIUS_STEPS_KM = [3, 10, 20, null]
// [경과일 이하, 단계]: 0~3일 → 3km, 4~7일 → 10km, 8~14일 → 20km, 그 뒤 → 조회 지역 전체
export const STEP_BY_DAYS = [[3, 0], [7, 1], [14, 2]]
const DAY_MS = 24 * 60 * 60 * 1000

/** 브라우저 기준 오늘 'YYYY-MM-DD'(사용자가 한국에 있으면 한국 날짜). */
export function todayLocal() {
  return new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

/** 실종 후 지난 날. 날짜는 'YYYY-MM-DD'(한국 날짜). 읽을 수 없으면 null. */
export function daysSince(lostDate, today) {
  const a = Date.parse(`${lostDate}T00:00:00Z`)
  const b = Date.parse(`${today}T00:00:00Z`)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / DAY_MS)
}

/** 경과일 → 자동 반경 단계(서버 recommended_step 과 같은 규칙). */
export function recommendedStep(days) {
  if (days == null) return RADIUS_STEPS_KM.length - 1
  for (const [limit, step] of STEP_BY_DAYS) if (days <= limit) return step
  return RADIUS_STEPS_KM.length - 1
}

/** 자동 단계에서 다음 단계로 넓어지는 경과일(서버 next_widen_day 와 같은 규칙). */
export function nextWidenDay(step) {
  const row = STEP_BY_DAYS.find(([, s]) => s === step)
  return row ? row[0] + 1 : null
}

/**
 * 검색 전 미리 보기용 반경. 지도에서 찍은 위치(location.lat/lng)와 실종 날짜가 있을 때만 만든다.
 * 서버 요약(run.radius)과 같은 모양으로 만들어 실종 지역 선택 창(RegionPicker)이 원과 안내를 그린다.
 */
export function previewRadius(location, lostDate, today) {
  if (!location?.lat || !location?.lng || !lostDate || location.region === '전체') return null
  const days = daysSince(lostDate, today)
  if (days == null || days < 0) return null
  const step = recommendedStep(days)
  const km = RADIUS_STEPS_KM[step]
  return {
    preview: true,
    applied: km != null,
    reason: km == null ? 'whole_region' : undefined,
    step,
    radius_km: km,
    next_radius_km: RADIUS_STEPS_KM[step + 1] ?? null,
    days_since_lost: days,
    auto: true,
    next_widen_day: nextWidenDay(step),
    lost_place: location.address || location.region,
    center: { lat: location.lat, lng: location.lng },
  }
}

/** "실종 후 N일 · M km" 안내 두 줄. [주 안내, 다음 단계 안내(없으면 '')]. */
export function radiusGuide(radius) {
  if (!radius) return ['', '']
  const days = radius.days_since_lost
  const when = days == null ? '' : days === 0 ? '오늘 실종됐어요. ' : `실종 후 ${days}일이 지났어요. `
  if (radius.radius_km == null) {
    return [`${when}시간이 꽤 지나 멀리 이동했을 수 있어 조회 지역 전체에서 찾아요.`, '']
  }
  const km = kmLabel(radius.radius_km).replace('반경 ', '')
  const main = radius.auto === false
    ? `넓히기를 선택해 실종 위치에서 ${km} 안을 찾아요.`
    : `${when}실종 위치에서 ${km} 안을 찾아요.`
  let next = ''
  if (radius.auto !== false && radius.next_widen_day != null) {
    const nextKm = RADIUS_STEPS_KM[radius.step + 1]
    next = nextKm == null
      ? `실종 후 ${radius.next_widen_day}일이 지나면 조회 지역 전체에서 찾아요.`
      : `실종 후 ${radius.next_widen_day}일이 지나면 ${nextKm}km로 넓혀 찾아요.`
  }
  return [main, next]
}

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
  return `${parts.join(' · ')} (구조된 읍·면·동 기준 직선거리, 모르면 관할 시·군·구 기준, 도로 거리 아님)`
}

/** 공고 카드에 붙일 거리 문구. */
export function distanceLabel(candidate) {
  if (!candidate || candidate.distance_basis == null) return ''
  if (candidate.distance_km == null) return '거리 미확인'
  // rescue_area: 구조 장소 읍면동 중심, jurisdiction_center: 관할 시군구 중심(구조 장소를 못 읽었을 때)
  return `약 ${candidate.distance_km}km(${candidate.distance_basis === 'rescue_area' ? '구조 장소 기준' : '관할 기준'})`
}

/** 반경 넓히기 질문(field=radius)에서 다음 단계와 버튼 문구를 꺼낸다. */
export function widenRadiusAction(questions, radius) {
  const q = (questions || []).find((item) => item.field === 'radius')
  if (!q || !Number.isInteger(q.next_step)) return null
  const km = RADIUS_STEPS_KM[q.next_step]
  return { step: q.next_step, label: `${kmLabel(km)}로 넓혀 찾기`, from: radius?.radius_km ?? null }
}
