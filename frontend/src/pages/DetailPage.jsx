import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import {
  errorMessage,
  formatDate,
  formatDateTime,
  kakaoSearchUrl,
  LOCATION_REASON,
  neuterLabel,
  noticeTitle,
  sexLabel,
  telHref
} from '../lib/format.js'
import KakaoMap from '../components/KakaoMap.jsx'
import NoticePhoto from '../components/NoticePhoto.jsx'
import SourceBadge from '../components/SourceBadge.jsx'

// 공고 상세 — 디자인: dasimanna-cards-detail.html
// /notices/:id            메인 목록에서 선택(서버 캐시의 공고)
// /notices/:id?run=:runId 검색 결과에서 선택(내 실행 기록의 후보 + 보호센터 위치 API)
export default function DetailPage() {
  const { noticeId } = useParams()
  const [params] = useSearchParams()
  const runId = params.get('run')
  const { user } = useAuth()
  const [item, setItem] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  useEffect(() => {
    setStatus('loading')
    const load = runId
      ? api(`/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(noticeId)}`)
      : api(`/notices/${encodeURIComponent(noticeId)}`, { auth: false })
    load
      .then((data) => {
        setItem(data)
        setStatus('ready')
        document.title = `다시 만나 · ${noticeTitle(data)} 공고`
      })
      .catch((err) => {
        setError(err)
        setStatus('error')
      })
  }, [noticeId, runId, user])

  const back = runId ? `/search?run=${encodeURIComponent(runId)}&page=${encodeURIComponent(params.get('page') || '1')}` : '/'
  const backLabel = runId ? '← 검색 결과로' : '← 전체 공고'

  if (status === 'loading') {
    return <main className="page-main detail-page"><p className="state-box">공고를 불러오고 있어요…</p></main>
  }
  if (status === 'error') {
    return (
      <main className="page-main detail-page">
        <div className="panel detail-not-found">
          <h1>공고를 찾지 못했어요.</h1>
          <p>{errorMessage(error)}</p>
          <Link className="primary-button" to={back}>{runId ? '검색으로 돌아가기' : '전체 공고로 돌아가기'}</Link>
        </div>
      </main>
    )
  }

  const care = item.care || {}
  const evidence = item.evidence
  return (
    <main className="page-main detail-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>공고 상세</span>
      </div>
      <div className="detail-heading">
        <div>
          <SourceBadge source={item.source} />
          <h1>{noticeTitle(item)}</h1>
          <p>{care.org || care.name || '보호기관 미확인'} · {item.happen_place || '발견 장소 미확인'}</p>
        </div>
        <Link className="text-link" to={back}>{backLabel}</Link>
      </div>
      <div className="detail-layout">
        <div className="detail-gallery">
          <NoticePhoto item={item} variant="main" />
          {item.photos?.length > 1 && (
            <div className="detail-thumbs">
              {item.photos.map((p, i) => (
                <a key={p} href={p} target="_blank" rel="noreferrer"><img className="detail-thumb-img" src={p} alt={`사진 ${i + 1}`} referrerPolicy="no-referrer" /></a>
              ))}
            </div>
          )}
          <p>{item.source === 'sample' ? '사진은 화면 구성을 위한 샘플입니다.' : '사진 출처: 공고 원본'}</p>
          {evidence && (
            <section className="panel evidence-panel" aria-label="일치 근거">
              <h2>이 후보를 보여 준 이유</h2>
              <p className="fineprint">점수 {item.score} · 같은 동물일 확률이 아니라 확인해 볼 유사 후보예요.</p>
              <EvidenceList title="일치" items={evidence.matched} tone="ok" />
              <EvidenceList title="불일치" items={evidence.mismatched} tone="bad" />
              <EvidenceList title="미확인" items={evidence.unknown} tone="unknown" />
            </section>
          )}
        </div>
        <section className="detail-information" aria-label="공고 정보">
          <div className="detail-status">
            <span className="sample-label">{item.process_state || '상태 미확인'}</span>
            <span>{item.notice_no || '공고번호 미확인'}</span>
          </div>
          <dl className="detail-facts">
            <Fact label="품종" value={item.breed} />
            <Fact label="성별" value={sexLabel(item.sex)} />
            <Fact label="색깔" value={item.color} />
            <Fact label="나이" value={item.age} />
            <Fact label="체중" value={item.weight} />
            <Fact label="중성화" value={neuterLabel(item.neuter)} />
            <Fact label="구조 위치" value={item.happen_place} />
            <Fact label="구조 날짜" value={formatDate(item.happen_date)} />
            <Fact label="공고 기간" value={item.notice_start ? `${formatDate(item.notice_start)} ~ ${formatDate(item.notice_end)}` : null} />
          </dl>
          <div className="detail-note">
            <strong>특징</strong>
            <p>{item.special_mark || '공고에 적힌 특징이 없어요.'}</p>
          </div>
          <div className="detail-note care-box">
            <strong>보호센터</strong>
            <p>
              {care.name || '보호센터 미확인'}
              <br />
              {care.address || '주소 미확인'}
              <br />
              {telHref(care.tel) ? <a className="text-link" href={telHref(care.tel)}>☎ {care.tel}</a> : '연락처 미확인'}
            </p>
            <CenterLocation item={item} runId={runId} />
          </div>
          <div className="detail-page-actions">
            <Link className="primary-button" to="/search">우리 아이 찾기</Link>
            <Link className="secondary-button" to={back}>목록으로</Link>
          </div>
          <p className="fineprint">
            조회 {formatDateTime(item.fetched_at)} 기준 정보예요. 실제 보호 여부와 공고 상태는 보호센터에 꼭 확인해 주세요.
          </p>
        </section>
      </div>
    </main>
  )
}

function Fact({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || '미확인'}</dd>
    </div>
  )
}

function EvidenceList({ title, items, tone }) {
  if (!items?.length) return null
  return (
    <div className={`evidence evidence-${tone}`}>
      <strong>{title}</strong>
      <ul>{items.map((t) => <li key={t}>{t}</li>)}</ul>
    </div>
  )
}

/** 보호센터 위치. 검색 결과 후보면 서버 위치 API(좌표 캐시), 아니면 카카오맵 링크. */
function CenterLocation({ item, runId }) {
  const [loc, setLoc] = useState(null)
  const [state, setState] = useState(runId ? 'loading' : 'link')
  const [error, setError] = useState(null)
  const address = item.care?.address

  function load() {
    setState('loading')
    api(`/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(item.id)}/location`)
      .then((body) => {
        setLoc(body)
        setState('ready')
      })
      .catch((err) => {
        setError(err)
        setState('error')
      })
  }

  useEffect(() => {
    if (runId) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, item.id])

  if (state === 'link') {
    const link = kakaoSearchUrl(address)
    return link ? <a className="text-link" href={link} target="_blank" rel="noreferrer">카카오맵에서 보호센터 주소 보기 ↗</a> : null
  }
  if (state === 'loading') return <p className="map-note">보호센터 위치를 확인하고 있어요…</p>
  if (state === 'error') {
    return (
      <p className="map-note">
        {errorMessage(error)} <button type="button" className="text-action" onClick={load}>다시 시도</button>
      </p>
    )
  }
  if (loc.status !== 'ok') {
    const link = kakaoSearchUrl(address)
    return (
      <p className="map-note">
        {LOCATION_REASON[loc.reason] || '위치를 표시할 수 없어요.'}{' '}
        {link && <a className="text-link" href={link} target="_blank" rel="noreferrer">카카오맵 검색 ↗</a>}
      </p>
    )
  }
  return <KakaoMap lat={loc.lat} lng={loc.lng} address={address} title={item.care?.name || '보호센터'} />
}
