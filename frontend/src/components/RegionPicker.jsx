import { useCallback, useEffect, useRef, useState } from 'react'
import { KAKAO_JS_KEY, loadKakaoSdk } from '../lib/kakao.js'
import { matchRegion } from '../lib/region.js'
import { kmLabel, previewRadius, radiusGuide, todayLocal } from '../lib/radius.js'

const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 } // 지도 첫 화면의 중심일 뿐, 선택 위치로 저장하지 않는다.

// withRadius: 우리 아이 찾기용. 창 안에서 실종 날짜를 받고, 위치를 고르는 즉시 검색 반경 원과 안내를 보여 준다.
//   선택 결과(onSelect)에 lost_date 를 함께 넘긴다. 게시판 글쓰기는 withRadius 없이 위치만 고른다.
export default function RegionPicker({
  open, regions, initial, onClose, onSelect, allowAll = true, title = '실종 지역 선택', withRadius = false, lostDate = '',
}) {
  const mapBox = useRef(null)
  const kakaoRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const circleRef = useRef(null)
  const [date, setDate] = useState(lostDate)
  const [state, setState] = useState(KAKAO_JS_KEY ? 'loading' : 'no_key')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [notice, setNotice] = useState('')
  const [picked, setPicked] = useState(initial?.lat ? initial : null)
  const [fallback, setFallback] = useState(initial?.region && !initial?.lat ? initial.region : '')

  const placeMarker = useCallback((lat, lng) => {
    const kakao = kakaoRef.current
    const map = mapRef.current
    if (!kakao || !map) return
    const pos = new kakao.maps.LatLng(lat, lng)
    if (!markerRef.current) markerRef.current = new kakao.maps.Marker({ map })
    markerRef.current.setPosition(pos)
    map.panTo(pos)
  }, [])

  const pickCoord = useCallback(
    (lat, lng) => {
      const kakao = kakaoRef.current
      if (!kakao) return
      placeMarker(lat, lng)
      const geocoder = new kakao.maps.services.Geocoder()
      geocoder.coord2RegionCode(lng, lat, (rows, status) => {
        if (status !== kakao.maps.services.Status.OK || !rows.length) {
          setPicked(null)
          setNotice('이 위치의 주소를 확인하지 못했어요. 다른 곳을 눌러 주세요.')
          return
        }
        const row = rows.find((r) => r.region_type === 'B') || rows[0]
        const region = matchRegion(row.region_1depth_name, regions)
        const address = [row.region_1depth_name, row.region_2depth_name, row.region_3depth_name].filter(Boolean).join(' ')
        if (!region) {
          setPicked(null)
          setNotice(`'${row.region_1depth_name}'은(는) 공고 검색 지역 목록에 없어요.`)
          return
        }
        setNotice('')
        setPicked({ region, address, lat, lng })
      })
    },
    [placeMarker, regions]
  )

  const initMap = useCallback(() => {
    if (!KAKAO_JS_KEY) return
    setState('loading')
    loadKakaoSdk()
      .then((kakao) => {
        if (!mapBox.current) return
        kakaoRef.current = kakao
        const start = initial?.lat ? initial : DEFAULT_CENTER
        const map = new kakao.maps.Map(mapBox.current, { center: new kakao.maps.LatLng(start.lat, start.lng), level: initial?.lat ? 5 : 8 })
        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT)
        mapRef.current = map
        markerRef.current = null
        circleRef.current = null // 새 지도이므로 이전 지도의 원은 버린다
        if (initial?.lat) placeMarker(initial.lat, initial.lng)
        kakao.maps.event.addListener(map, 'click', (e) => pickCoord(e.latLng.getLat(), e.latLng.getLng()))
        setState('ready')
      })
      .catch(() => setState('error'))
  }, [initial, pickCoord, placeMarker])

  useEffect(() => {
    if (!open) return
    setDate(lostDate)
    initMap()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // 고른 위치 + 실종 날짜 → 반경(검색과 같은 기준표). 위치나 날짜가 바뀌면 원을 바로 다시 그린다.
  const radius = withRadius ? previewRadius(picked, date, todayLocal()) : null
  const radiusKm = radius?.radius_km ?? null
  useEffect(() => {
    const kakao = kakaoRef.current
    const map = mapRef.current
    if (!withRadius || !kakao || !map || state !== 'ready') return
    if (circleRef.current) {
      circleRef.current.setMap(null)
      circleRef.current = null
    }
    if (!picked?.lat || radiusKm == null) return
    const center = new kakao.maps.LatLng(picked.lat, picked.lng)
    circleRef.current = new kakao.maps.Circle({
      map, center, radius: radiusKm * 1000,
      strokeWeight: 3, strokeColor: '#c98f12', strokeOpacity: 0.95,
      fillColor: '#f5d76e', fillOpacity: 0.28,
    })
    map.setBounds(circleRef.current.getBounds(), 8, 8, 8, 8)
  }, [withRadius, state, picked?.lat, picked?.lng, radiusKm])

  function search(event) {
    event.preventDefault()
    const kakao = kakaoRef.current
    const q = query.trim()
    if (!kakao || !q) return
    setSearching(true)
    setNotice('')
    const geocoder = new kakao.maps.services.Geocoder()
    geocoder.addressSearch(q, (rows, status) => {
      if (status === kakao.maps.services.Status.OK && rows.length) {
        setSearching(false)
        setResults(rows.slice(0, 8).map((r) => ({ label: r.address_name, lat: Number(r.y), lng: Number(r.x) })))
        return
      }
      new kakao.maps.services.Places().keywordSearch(q, (places, pstatus) => {
        setSearching(false)
        if (pstatus === kakao.maps.services.Status.OK && places.length) {
          setResults(places.slice(0, 8).map((p) => ({ label: `${p.place_name} · ${p.address_name}`, lat: Number(p.y), lng: Number(p.x) })))
        } else {
          setResults([])
          setNotice('검색 결과가 없어요. 동 이름이나 도로명으로 다시 찾아보세요.')
        }
      })
    })
  }

  function choose(item) {
    setResults([])
    pickCoord(item.lat, item.lng)
  }

  // withRadius 일 때는 실종 날짜도 같이 넘긴다(폼의 실종 날짜와 같은 값).
  const withDate = (value) => (withRadius ? { ...value, lost_date: date } : value)

  function confirm() {
    if (state === 'ready' || state === 'loading') {
      if (picked) onSelect(withDate(picked))
    } else if (fallback) {
      onSelect(withDate({ region: fallback, address: fallback === '전체' ? '' : fallback }))
    }
  }

  if (!open) return null
  const today = todayLocal()
  const dateOk = !withRadius || (Boolean(date) && date <= today)
  const canConfirm = dateOk && (state === 'ready' ? Boolean(picked) : state === 'no_key' || state === 'error' ? Boolean(fallback) : false)
  const [guide, nextGuide] = radius ? radiusGuide(radius) : ['', '']

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal region-modal" role="dialog" aria-modal="true" aria-labelledby="region-modal-title">
        <div className="modal-head">
          <h2 id="region-modal-title">{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="닫기">×</button>
        </div>

        {withRadius && (
          <label className="region-date">
            <span>실종 날짜 <em className="req">필수</em></span>
            <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} />
          </label>
        )}

        {(state === 'loading' || state === 'ready') && (
          <>
            <form className="region-search" onSubmit={search} role="search">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="주소나 장소를 검색하세요 (예: 강서구 화곡동, 서울숲)"
                aria-label="주소 검색"
                autoFocus
              />
              <button type="submit" className="secondary-button" disabled={searching || state !== 'ready'}>
                {searching ? '찾는 중…' : '검색'}
              </button>
            </form>
            {results.length > 0 && (
              <ul className="region-results">
                {results.map((r) => (
                  <li key={`${r.label}-${r.lat}-${r.lng}`}>
                    <button type="button" onClick={() => choose(r)}>{r.label}</button>
                  </li>
                ))}
              </ul>
            )}
            <div ref={mapBox} className="region-map" aria-label="실종 지역 지도. 지도를 눌러 위치를 고르세요." />
            {state === 'loading' && <p className="map-note">지도를 불러오는 중…</p>}
            {withRadius ? (
              // 위치를 고르면 반경 안내, 고르기 전에는 사용법 안내
              <p className="map-note region-guide" role="status">
                {guide
                  ? <><strong>{guide}</strong>{nextGuide && <> {nextGuide}</>}{radiusKm != null && ' 거리는 공고를 맡은 시·군·구 중심까지로 재요.'}</>
                  : '지도를 누르거나 주소를 검색해 실종 위치를 고르면 찾을 범위가 지도에 표시돼요.'}
              </p>
            ) : (
              <p className="map-note">지도를 누르면 그 위치로 실종 지역이 바뀌어요. 공고는 해당 시·도 기준으로 찾아요.</p>
            )}
          </>
        )}

        {(state === 'no_key' || state === 'error') && (
          <div className="region-fallback">
            <p className="map-note">
              {state === 'error' ? '지도를 불러오지 못했어요. ' : '지도 기능이 설정되지 않았어요. '}
              시·도를 목록에서 골라 주세요.
              {state === 'error' && <button type="button" className="text-action" onClick={initMap}>지도 다시 시도</button>}
            </p>
            <select value={fallback} onChange={(e) => setFallback(e.target.value)} aria-label="시·도 선택">
              <option value="">선택</option>
              {regions.map((r) => <option key={r.code} value={r.name}>{r.name}</option>)}
            </select>
          </div>
        )}

        {notice && <p className="auth-error" role="alert">{notice}</p>}

        <div className="modal-foot">
          <div className="region-picked" aria-live="polite">
            {state === 'ready' ? (picked ? <>선택한 위치 <strong>{picked.address || picked.region}</strong>{radiusKm != null && <> · {kmLabel(radiusKm)}</>}</> : '아직 선택한 위치가 없어요.') : null}
            {!dateOk && <span className="region-date-error"> 실종 날짜를 확인해 주세요.</span>}
          </div>
          {allowAll && (
            <button type="button" className="text-action" disabled={!dateOk} onClick={() => onSelect(withDate({ region: '전체', address: '' }))}>
              지역 상관없이 전체에서 찾기
            </button>
          )}
          <button type="button" className="primary-button" disabled={!canConfirm} onClick={confirm}>선택 완료</button>
        </div>
      </div>
    </div>
  )
}
