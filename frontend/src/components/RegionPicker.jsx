import { useCallback, useEffect, useRef, useState } from 'react'
import { KAKAO_JS_KEY, loadKakaoSdk } from '../lib/kakao.js'
import { matchRegion } from '../lib/region.js'

const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 } // 서울시청(지도 첫 화면 위치일 뿐, 값으로 쓰지 않음)

/**
 * 실종 지역 선택 모달.
 * 위: 카카오 주소 검색, 아래: 지도. 검색 결과나 지도를 누르면 그 위치의 주소와 시·도를 고른다.
 * 결과: { region: 공식 시·도 이름 | '전체', address, lat, lng }
 * allowAll=false 이면 '전체' 선택 버튼을 숨긴다(게시글 등록처럼 위치가 꼭 필요한 곳).
 */
export default function RegionPicker({ open, regions, initial, onClose, onSelect, allowAll = true, title = '실종 지역 선택' }) {
  const mapBox = useRef(null)
  const kakaoRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
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

  // 좌표 → 주소·시도. 시도는 공식 목록 이름으로 맞추고, 못 맞추면 선택을 막는다.
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
        if (initial?.lat) placeMarker(initial.lat, initial.lng)
        kakao.maps.event.addListener(map, 'click', (e) => pickCoord(e.latLng.getLat(), e.latLng.getLng()))
        setState('ready')
      })
      .catch(() => setState('error'))
  }, [initial, pickCoord, placeMarker])

  useEffect(() => {
    if (!open) return
    initMap()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // 모달을 열 때마다 지도를 새로 그린다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

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
      // 주소로 못 찾으면 장소 이름(공원·역 등)으로 다시 찾는다.
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

  function confirm() {
    if (state === 'ready' || state === 'loading') {
      if (picked) onSelect(picked)
    } else if (fallback) {
      onSelect({ region: fallback, address: fallback === '전체' ? '' : fallback })
    }
  }

  if (!open) return null
  const canConfirm = state === 'ready' ? Boolean(picked) : state === 'no_key' || state === 'error' ? Boolean(fallback) : false

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal region-modal" role="dialog" aria-modal="true" aria-labelledby="region-modal-title">
        <div className="modal-head">
          <h2 id="region-modal-title">{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="닫기">×</button>
        </div>

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
            <p className="map-note">지도를 누르면 그 위치로 실종 지역이 바뀌어요. 공고는 해당 시·도 기준으로 찾아요.</p>
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
            {state === 'ready' ? (picked ? <>선택한 위치 <strong>{picked.address || picked.region}</strong></> : '아직 선택한 위치가 없어요.') : null}
          </div>
          {allowAll && (
            <button type="button" className="text-action" onClick={() => onSelect({ region: '전체', address: '' })}>
              지역 상관없이 전체에서 찾기
            </button>
          )}
          <button type="button" className="primary-button" disabled={!canConfirm} onClick={confirm}>선택 완료</button>
        </div>
      </div>
    </div>
  )
}
