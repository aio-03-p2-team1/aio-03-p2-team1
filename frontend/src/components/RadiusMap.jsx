import { useEffect, useRef, useState } from 'react'
import { loadKakaoSdk } from '../lib/kakao.js'
import { kmLabel, previousRadiusKm } from '../lib/radius.js'

// 검색 반경 지도: 실종 위치(서버가 좌표로 바꾼 동 단위 주소)와 반경 원을 그린다.
// 공고 마커는 찍지 않는다(관할 구청 중심 좌표라 실제 발견 위치처럼 보일 수 있음).
export default function RadiusMap({ radius }) {
  const boxRef = useRef(null)
  const [state, setState] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const center = radius?.center
  const km = radius?.radius_km
  const prevKm = previousRadiusKm(radius)

  useEffect(() => {
    if (!center || km == null) return undefined
    let cancelled = false
    setState('loading')
    loadKakaoSdk()
      .then((kakao) => {
        if (cancelled || !boxRef.current) return
        const position = new kakao.maps.LatLng(center.lat, center.lng)
        const map = new kakao.maps.Map(boxRef.current, { center: position, level: 7 })
        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT)
        new kakao.maps.Marker({ map, position })
        if (prevKm) {
          // 넓히기 전 반경(점선)
          new kakao.maps.Circle({
            map, center: position, radius: prevKm * 1000,
            strokeWeight: 2, strokeColor: '#b9a77c', strokeOpacity: 0.9, strokeStyle: 'dashed',
            fillColor: '#ffffff', fillOpacity: 0
          })
        }
        const circle = new kakao.maps.Circle({
          map, center: position, radius: km * 1000,
          strokeWeight: 2, strokeColor: '#d9a520', strokeOpacity: 0.9,
          fillColor: '#f5d76e', fillOpacity: 0.18
        })
        map.setBounds(circle.getBounds())
        setState('ready')
      })
      .catch(() => {
        if (!cancelled) setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [center?.lat, center?.lng, km, prevKm, attempt])

  if (!radius?.applied || !center || km == null) return null
  return (
    <div className="radius-map panel">
      <div className="radius-map-head">
        <strong>검색 범위 · {kmLabel(km)}</strong>
        <span>{radius.lost_place} 기준 · 직선거리</span>
      </div>
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
