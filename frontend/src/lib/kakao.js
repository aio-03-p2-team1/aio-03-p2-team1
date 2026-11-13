// 카카오 지도 JavaScript SDK 로더.
// autoload=false 로 페이지당 한 번만 로드해 재사용하고, 실패하면 다음 호출에서 다시 시도한다(prompt.md 6.2).
// 주소 검색·좌표→주소 변환을 위해 services 라이브러리를 함께 받는다.

export const KAKAO_JS_KEY = import.meta.env?.VITE_KAKAO_JS_KEY || ''

let sdkPromise = null

export function loadKakaoSdk() {
  if (!KAKAO_JS_KEY) return Promise.reject(new Error('no_key'))
  if (window.kakao?.maps?.services) return Promise.resolve(window.kakao)
  if (!sdkPromise) {
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(KAKAO_JS_KEY)}&autoload=false&libraries=services`
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
