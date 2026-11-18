import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Stage, Layer } from 'react-konva'
import { api } from '../lib/api.js'
import { errorMessage } from '../lib/format.js'
import { CanvasItem, PosterBackground, usePosterBackground } from '../components/PosterCanvasItem.jsx'

/** 화면 폭에 맞춰 전단지를 줄여 보여 줄 배율(최대 1배). */
function useFitScale(width) {
  const box = useRef(null)
  const [scale, setScale] = useState(0.6)
  useEffect(() => {
    const el = box.current
    if (!el || !width) return
    const fit = () => setScale(Math.min(1, el.clientWidth / width))
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)
    return () => observer.disconnect()
  }, [width])
  return [box, scale]
}

// 전단지 상세: 저장한 전단지를 읽기 전용으로 보여 주고, 오른쪽 위 '수정'으로 편집기(/poster?edit=)로 보낸다.
export default function PosterDetailPage() {
  const { posterId } = useParams()
  const [poster, setPoster] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [box, scale] = useFitScale(poster?.width)
  const sorted = useMemo(() => (poster?.components || []).filter((item) => item.type !== 'background').sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0)), [poster])
  const background = usePosterBackground(poster)

  useEffect(() => {
    let live = true
    setStatus('loading')
    api(`/posters/${encodeURIComponent(posterId)}`)
      .then((data) => {
        if (!live) return
        setPoster(data)
        setStatus('ready')
        const title = data.components?.find((c) => c.fieldKey === 'title')?.content
        document.title = `다시 만나 · ${title || '실종 전단지'}`
      })
      .catch((err) => {
        if (!live) return
        setError(err)
        setStatus('error')
      })
    return () => { live = false }
  }, [posterId])

  if (status === 'loading') return <main className="page-main"><p className="state-box">전단지를 불러오고 있어요…</p></main>
  if (status === 'error') {
    return (
      <main className="page-main">
        <div className="panel detail-not-found">
          <h1>전단지를 찾지 못했어요.</h1>
          <p>{errorMessage(error)}</p>
          <Link className="primary-button" to="/my">마이페이지로 돌아가기</Link>
        </div>
      </main>
    )
  }

  const field = (key) => poster.components.find((c) => c.fieldKey === key)?.content?.trim()
  return (
    <main className="page-main poster-detail-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><Link to="/my">마이페이지</Link><span aria-hidden="true">›</span><span>전단지</span>
      </div>
      <div className="poster-detail-head">
        <div>
          <span className="eyebrow">내가 만든 실종 전단지</span>
          <h1>{field('title') || '실종 전단지'}</h1>
          <p>{[field('pet_name'), field('lost_place')].filter(Boolean).join(' · ') || '전단지 내용을 확인해 주세요.'}</p>
        </div>
        <Link className="primary-button" to={`/poster?edit=${encodeURIComponent(poster.id)}`}>수정</Link>
      </div>
      <section className="panel poster-detail-canvas" aria-label="전단지 미리보기">
        {background.error && <p role="alert">전단지 배경을 불러오지 못했습니다.</p>}
        <div ref={box} className="poster-detail-fit">
          <div className="poster-detail-scale" style={{ width: poster.width * scale, height: poster.height * scale }}>
            <Stage width={poster.width * scale} height={poster.height * scale} scaleX={scale} scaleY={scale} listening={false}>
              <Layer>
                <PosterBackground poster={poster} image={background.image} />
                {sorted.map((item) => <CanvasItem key={item.id} item={item} readOnly />)}
              </Layer>
            </Stage>
          </div>
        </div>
      </section>
      <p className="fineprint poster-detail-note">
        인쇄나 이미지 저장은 수정 화면의 'PNG 다운로드'·'PDF / 인쇄'를 이용해 주세요.
      </p>
    </main>
  )
}
