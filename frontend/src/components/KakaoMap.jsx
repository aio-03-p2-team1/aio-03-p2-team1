import { useCallback, useEffect, useRef, useState } from 'react'
import { kakaoSearchUrl } from '../lib/format.js'

const JS_KEY = import.meta.env.VITE_KAKAO_JS_KEY
let sdkPromise = null

// SDK 는 autoload=false 로 페이지당 한 번만 로드해 재사용한다. 실패하면 다음 시도에서 다시 로드한다.
function loadSdk() {
  if (window.kakao?.maps?.LatLng) return Promise.resolve(window.kakao)
  if (!sdkPromise) {
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(JS_KEY)}&autoload=false`
      script.async = true
      script.onload = () => {
        if (!window.kakao?.maps) return reject(new Error('sdk'))
        window.kakao.maps.load(() => resolve(window.kakao))
      }
      script.onerror = () => {
        script.remove()
        reject(new Error('sdk'))
      }
      document.head.appendChild(script)
    }).catch((err) => {
      sdkPromise = null
      throw err
    })
  }
  return sdkPromise
}

/** lat/lng 가 있을 때만 마커를 찍는다. 지도를 못 쓰면 카카오맵 주소 검색 링크로 대체한다. */
export default function KakaoMap({ lat, lng, address, title }) {
  const box = useRef(null)
  const [state, setState] = useState(JS_KEY ? 'loading' : 'no_key')

  const draw = useCallback(() => {
    if (!JS_KEY) return
    setState('loading')
    loadSdk()
      .then((kakao) => {
        if (!box.current) return
        const center = new kakao.maps.LatLng(lat, lng)
        const map = new kakao.maps.Map(box.current, { center, level: 4 })
        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT)
        new kakao.maps.Marker({ map, position: center, title })
        setState('ready')
      })
      .catch(() => setState('error'))
  }, [lat, lng, title])

  useEffect(() => {
    draw()
  }, [draw])

  const link = kakaoSearchUrl(address)
  return (
    <div className="map-wrap">
      {state !== 'no_key' && <div ref={box} className="map-box" aria-label={`${title} 위치 지도`} />}
      {state === 'loading' && <p className="map-note">지도를 불러오는 중…</p>}
      {state === 'error' && (
        <p className="map-note">
          지도를 불러오지 못했어요. <button type="button" className="text-action" onClick={draw}>다시 시도</button>
        </p>
      )}
      {(state === 'no_key' || state === 'error') && link && (
        <a className="text-link" href={link} target="_blank" rel="noreferrer">카카오맵에서 주소 검색 ↗</a>
      )}
    </div>
  )
}
