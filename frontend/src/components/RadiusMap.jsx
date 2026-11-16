import { useEffect, useRef, useState } from 'react'
import { loadKakaoSdk } from '../lib/kakao.js'
import { kmLabel, previousRadiusKm, radiusGuide } from '../lib/radius.js'

// 검색 반경 지도: 실종 위치(사용자가 찍은 좌표, 없으면 서버가 주소로 구한 좌표)와 반경 원을 그린다.
// 공고 마커는 찍지 않는다(관할 구청 중심 좌표라 실제 발견 위치처럼 보일 수 있음).
// 검색 전 범위 미리 보기는 실종 지역 선택 창(RegionPicker withRadius)이 맡는다.
export default function RadiusMap({ radius }) {
  const boxRef = useRef(null)
  const [state, setState] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const center = radius?.center
  const km = radius?.radius_km
  const prevKm = previousRadiusKm(radius)

  // 지도는 한 번만 만들고, 위치·날짜가 바뀌면 마커와 원만 바꿔 그린다.
  // (매번 새 지도를 만들면 같은 칸에 지도가 겹쳐 쌓이고 이전 원이 남는다.)
  const mapRef = useRef(null)
  const overlaysRef = useRef([])

  useEffect(() => () => {
    overlaysRef.current.forEach((o) => o.setMap(null))
    overlaysRef.current = []
    mapRef.current = null
  }, [])

  useEffect(() => {
    if (!center || km == null) return undefined
    let cancelled = false
    setState('loading')
    loadKakaoSdk()
      .then((kakao) => {
        if (cancelled || !boxRef.current) return
        const position = new kakao.maps.LatLng(center.lat, center.lng)
        if (!mapRef.current || mapRef.current.box !== boxRef.current) {
          const map = new kakao.maps.Map(boxRef.current, { center: position, level: 7 })
          map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT)
          mapRef.current = { map, box: boxRef.current }
        }
        const { map } = mapRef.current
        overlaysRef.current.forEach((o) => o.setMap(null))
        const overlays = [new kakao.maps.Marker({ map, position })]
        if (prevKm) {
          // 넓히기 전 반경(점선)
          overlays.push(new kakao.maps.Circle({
            map, center: position, radius: prevKm * 1000,
            strokeWeight: 2, strokeColor: '#b9a77c', strokeOpacity: 0.9, strokeStyle: 'dashed',
            fillColor: '#ffffff', fillOpacity: 0
          }))
        }
        const circle = new kakao.maps.Circle({
          map, center: position, radius: km * 1000,
          strokeWeight: 3, strokeColor: '#c98f12', strokeOpacity: 0.95,
          fillColor: '#f5d76e', fillOpacity: 0.28
        })
        overlays.push(circle)
        overlaysRef.current = overlays
        map.relayout()
        // 여백을 작게 줘서 원이 지도 칸을 최대한 채우게 한다(기본 여백 32px 이면 원이 너무 작게 보임).
        map.setBounds(circle.getBounds(), 8, 8, 8, 8)
        setState('ready')
      })
      .catch(() => {
        if (!cancelled) setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [center?.lat, center?.lng, km, prevKm, attempt])

  const [guide, nextGuide] = radiusGuide(radius)
  // 실종 후 2주가 지나 반경 없이 찾는 경우: 지도 없이 안내만 보여 준다.
  if (radius && km == null && radius.days_since_lost != null && radius.reason === 'whole_region') {
    return (
      <div className="radius-map panel" role="status">
        <div className="radius-map-head"><strong>검색 범위 · 조회 지역 전체</strong></div>
        <p className="radius-guide">{guide}</p>
      </div>
    )
  }
  if (!radius?.applied || !center || km == null) return null
  return (
    <div className="radius-map panel">
      <div className="radius-map-head">
        <strong>검색 범위 · {kmLabel(km)}</strong>
        <span>{radius.lost_place} 기준 · 직선거리</span>
      </div>
      {/* 실종 후 경과일과 반경 안내. 결과 화면은 서버 값(days_since_lost 등)을 그대로 쓴다. */}
      <p className="radius-guide" role="status">
        {guide}
        {nextGuide && <span className="radius-guide-next"> {nextGuide}</span>}
      </p>
      {/* 지도 SDK 가 이 div 안을 직접 그리므로 React 자식을 두지 않는다. */}
      <div ref={boxRef} className="radius-map-box" role="img" aria-label={`${radius.lost_place} 중심 ${kmLabel(km)} 검색 범위 지도`} />
      {state === 'loading' && <p className="radius-map-note">지도를 불러오고 있어요…</p>}
      {state === 'error' && (
        <p className="radius-map-note">
          지도를 불러오지 못했어요. {radius.lost_place} 중심 {kmLabel(km)} 안에서 찾았어요.{' '}
          <button type="button" className="text-action" onClick={() => setAttempt((n) => n + 1)}>지도 다시 시도</button>
        </p>
      )}
      {prevKm && <p className="radius-map-note">점선은 넓히기 전 범위({kmLabel(prevKm)})예요.</p>}
    </div>
  )
}
