import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api.js'
import { errorMessage, formatDate, formatDateTime, noticeTitle, sourceLabel, SPECIES_OPTIONS } from '../lib/format.js'
import NoticePhoto from '../components/NoticePhoto.jsx'
import StoryBanner from '../components/StoryBanner.jsx'
import { useRegions } from './useRegions.js'

const ROWS = 20

export default function BoardPage() {
  const [species, setSpecies] = useState('all')
  const [regionCode, setRegionCode] = useState('')
  const [days, setDays] = useState(14)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [items, setItems] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [reload, setReload] = useState(0)
  const regions = useRegions()

  useEffect(() => {
    document.title = '다시 만나 · 전체 공고'
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const query = new URLSearchParams({ species, days: String(days), page: String(page), rows: String(ROWS) })
    if (regionCode) query.set('region_code', regionCode)
    setStatus(page === 1 ? 'loading' : 'more')
    api(`/notices?${query}`, { auth: false, signal: controller.signal })
      .then((body) => {
        setData(body)
        setItems((prev) => (page === 1 ? body.items : [...prev, ...body.items]))
        setStatus('ready')
        setError(null)
      })
      .catch((err) => {
        if (err.name === 'AbortError') return
        setError(err)
        setStatus('error')
      })
    return () => controller.abort()
  }, [species, regionCode, days, page, reload])

  function changeFilter(setter) {
    return (event) => {
      setter(event.target.value)
      setPage(1)
    }
  }

  const hasMore = data && items.length < data.total_count

  return (
    <main className="page-main board-page">
      <StoryBanner />
      <div className="page-heading board-heading">
        <h1>보호 중인 동물 공고</h1>
        <Link to="/search" className="primary-button">우리 아이 찾기</Link>
        <div className="filters">
          <label>
            동물 종류
            <select value={species} onChange={changeFilter(setSpecies)}>
              {[...SPECIES_OPTIONS.slice(3), ...SPECIES_OPTIONS.slice(0, 3)].map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label>
            지역
            <select value={regionCode} onChange={changeFilter(setRegionCode)} disabled={!regions.list.length}>
              <option value="">전체 지역</option>
              {regions.list.map((r) => (
                <option key={r.code} value={r.code}>{r.name}</option>
              ))}
            </select>
          </label>
          <label>
            기간
            <select value={days} onChange={changeFilter((v) => setDays(Number(v)))}>
              <option value={7}>최근 7일</option>
              <option value={14}>최근 14일</option>
              <option value={30}>최근 30일</option>
            </select>
          </label>
        </div>
      </div>

      <section className="board-list-section" aria-label="보호 중인 동물 공고 목록">

        {status === 'loading' && <p className="state-box">공고를 불러오고 있어요…</p>}
        {status === 'error' && (
          <div className="state-box state-error" role="alert">
            <strong>공고를 불러오지 못했어요.</strong>
            <p>{errorMessage(error)}</p>
            <button type="button" className="secondary-button" onClick={() => setReload((n) => n + 1)}>다시 시도</button>
          </div>
        )}
        {status !== 'loading' && status !== 'error' && items.length === 0 && (
          <p className="empty-results">선택한 조건의 공고가 없어요.</p>
        )}
        {items.length > 0 && status !== 'loading' && (
          <div className="board-list" aria-live="polite">
            {items.map((item) => (
              <Link key={item.id} className="post-card" to={`/notices/${encodeURIComponent(item.id)}`}>
                <NoticePhoto item={item} />
                <span className="post-card-body">
                  <span className="sample-label">{item.process_state || '상태 미확인'}</span>
                  <strong>{noticeTitle(item)}</strong>
                  <p>{item.happen_place || '발견 장소 미확인'} · {formatDate(item.happen_date)}</p>
                  <small>{item.special_mark ? item.special_mark.slice(0, 62) + (item.special_mark.length > 62 ? '…' : '') : '특징 정보 없음'}</small>
                </span>
              </Link>
            ))}
          </div>
        )}
        {hasMore && status !== 'loading' && (
          <div className="load-more">
            <button type="button" className="secondary-button" disabled={status === 'more'} onClick={() => setPage((p) => p + 1)}>
              {status === 'more' ? '불러오는 중…' : `더 보기 (${items.length}/${data.total_count})`}
            </button>
          </div>
        )}
      </section>
      {data && (status === 'ready' || status === 'more') && (
        <div className="board-data-note" aria-label="공고 데이터 조회 정보">
          <span>{data.data_source === 'api' ? '공공데이터포털' : sourceLabel(data.data_source)}</span>
          <span>조회 범위 {formatDate(data.period.start)}~{formatDate(data.period.end)}</span>
          <span>전체 {Number(data.total_count).toLocaleString('ko-KR')}건</span>
          <span>{formatDateTime(data.fetched_at)} 조회</span>
        </div>
      )}
    </main>
  )
}
