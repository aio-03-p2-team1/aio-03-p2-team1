import { useEffect, useRef, useState } from 'react'
import { KAKAO_JS_KEY, loadKakaoSdk } from '../lib/kakao.js'
import { kakaoSearchUrl } from '../lib/format.js'

/**
 * 공고 상세 '구조 위치' 값 + 지도 버튼(🗺️).
 * 버튼을 누르면 작은 창에 구조 위치 지도를 띄우고, 창 밖을 누르거나 Esc 를 누르면 닫는다.
 *
 * 구조 위치(happenPlace)는 좌표 없이 글로만 오므로 브라우저 카카오 SDK 로 찾는다.
 * 주소 검색 → 실패하면 장소 검색 순서. 찾지 못하면 임의 마커를 찍지 않고 카카오맵 검색 링크만 준다.
 * 찾은 좌표는 이 화면에서만 쓰고 저장하지 않는다.
 */
export default function RescueLocation({ place }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!place) return <>미확인</>
  return (
    <span className="rescue-location" ref={wrap}>
      {place}
      <button
        type="button"
        className="rescue-map-button"
        aria-label="구조 위치 지도 보기"
        aria-expanded={open}
        title="구조 위치 지도 보기"
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">🗺️</span>
      </button>
      {open && <RescueMapPopover place={place} onClose={() => setOpen(false)} />}
    </span>
  )
}

function RescueMapPopover({ place, onClose }) {
  const box = useRef(null)
  const [state, setState] = useState(KAKAO_JS_KEY ? 'loading' : 'no_key') // loading | ready | approx | not_found | error | no_key
  const [found, setFound] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!KAKAO_JS_KEY) return
    let alive = true
    setState('loading')
    loadKakaoSdk()
      .then((kakao) => locate(kakao, place))
      .then((result) => {
        if (!alive) return
        if (!result) return setState('not_found')
        const kakao = window.kakao
        const center = new kakao.maps.LatLng(result.lat, result.lng)
        const map = new kakao.maps.Map(box.current, { center, level: 4 })
        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT)
        new kakao.maps.Marker({ map, position: center, title: '구조 위치' })
        setFound(result.label)
        setState(result.exact ? 'ready' : 'approx')
      })
      .catch(() => alive && setState('error'))
    return () => {
      alive = false
    }
  }, [place, attempt])

  const link = kakaoSearchUrl(place)
  const showMap = state === 'loading' || state === 'ready' || state === 'approx'
  return (
    <div className="rescue-map-popover" role="dialog" aria-label="구조 위치 지도">
      <div className="rescue-map-head">
        <strong>구조 위치</strong>
        <button type="button" className="modal-close" onClick={onClose} aria-label="닫기">×</button>
      </div>
      {showMap && <div ref={box} className="rescue-map-box" />}
      {state === 'loading' && <p className="map-note">지도를 불러오는 중…</p>}
      {state === 'approx' && <p className="map-note">'{found}' 검색 결과 위치예요. 실제 구조 지점과 다를 수 있어요.</p>}
      {state === 'ready' && found && found !== place && <p className="map-note">주소 검색 결과: {found}</p>}
      {state === 'not_found' && <p className="map-note">이 구조 위치를 지도에서 찾지 못했어요.</p>}
      {state === 'no_key' && <p className="map-note">지도 기능이 설정되지 않았어요.</p>}
      {state === 'error' && (
        <p className="map-note">
          지도를 불러오지 못했어요. <button type="button" className="text-action" onClick={() => setAttempt((n) => n + 1)}>다시 시도</button>
        </p>
      )}
      {link && <a className="text-link" href={link} target="_blank" rel="noreferrer">카카오맵에서 보기 ↗</a>}
    </div>
  )
}

/** 주소 검색(정확) → 장소 검색(대략) 순서로 좌표를 찾는다. 못 찾으면 null. */
function locate(kakao, place) {
  const { services } = kakao.maps
  const ok = services.Status.OK
  const valid = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && lat >= 33 && lat <= 39 && lng >= 124 && lng <= 132
  return new Promise((resolve) => {
    new services.Geocoder().addressSearch(place, (rows, status) => {
      const r = status === ok && rows[0]
      if (r && valid(Number(r.y), Number(r.x))) {
        return resolve({ lat: Number(r.y), lng: Number(r.x), label: r.address_name, exact: true })
      }
      new services.Places().keywordSearch(place, (items, pstatus) => {
        const p = pstatus === ok && items[0]
        if (p && valid(Number(p.y), Number(p.x))) {
          return resolve({ lat: Number(p.y), lng: Number(p.x), label: p.place_name || p.address_name, exact: false })
        }
        resolve(null)
      })
    })
  })
}
