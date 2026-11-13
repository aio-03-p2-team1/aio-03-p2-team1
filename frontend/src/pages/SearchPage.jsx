import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { errorMessage, formatDate, formatDateTime, noticeTitle, runStatusLabel, runSummary, scopeText } from '../lib/format.js'
import NoticePhoto from '../components/NoticePhoto.jsx'
import RegionPicker from '../components/RegionPicker.jsx'
import SpeciesPicker from '../components/SpeciesPicker.jsx'
import SourceBadge from '../components/SourceBadge.jsx'
import { useToast } from '../components/Toast.jsx'
import { useRegions } from './useRegions.js'

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
// 실종 날짜 기본값은 오늘. 지역은 모달에서 고른 위치(공식 시·도 + 주소)를 쓴다.
const initialForm = () => ({ species: '', lost_date: today(), description: '' })

// 우리 아이 찾기 — 디자인: dasimanna-cards-search.html
export default function SearchPage() {
  const regions = useRegions()
  const toast = useToast()
  const [form, setForm] = useState(initialForm)
  const [location, setLocation] = useState(null) // { region, address, lat?, lng? }
  const [regionOpen, setRegionOpen] = useState(false)
  const [photo, setPhoto] = useState('')
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])

  const [params] = useSearchParams()
  const runParam = params.get('run')

  useEffect(() => {
    document.title = '다시 만나 · 우리 아이 찾기'
    loadHistory()
  }, [])

  // 마이페이지 검색 기록에서 들어오면(?run=) 그 결과를 바로 보여 준다.
  useEffect(() => {
    if (runParam) openHistory(runParam)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runParam])

  function loadHistory() {
    api('/runs?limit=8').then((body) => setHistory(body.runs)).catch(() => setHistory([]))
  }

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }))

  function onPhoto(event) {
    const file = event.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) return toast('이미지 파일을 선택해 주세요.')
    setPhoto((old) => {
      if (old) URL.revokeObjectURL(old)
      return URL.createObjectURL(file)
    })
  }

  async function submit(criteria, threadId) {
    setBusy(true)
    setError(null)
    try {
      const body = { criteria, reflection_enabled: true }
      if (threadId) body.thread_id = threadId
      const result = await api('/searches', { method: 'POST', body })
      setRun(result)
      loadHistory()
      if (result.status === 'awaiting_input') toast('추가 정보가 필요해요.')
      document.getElementById('results-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  function onSubmit(event) {
    event.preventDefault()
    const criteria = {}
    for (const [k, v] of Object.entries(form)) if (v.trim()) criteria[k] = v.trim()
    if (location?.region) criteria.region = location.region
    if (location?.address) criteria.lost_place = location.address
    // 이어지는 질문에 답하는 중이면 같은 세션(thread)으로 보낸다.
    submit(criteria, run?.status === 'awaiting_input' ? run.thread_id : undefined)
  }

  function widenRegion() {
    setLocation({ region: '전체', address: '' })
    submit({ region: '전체' }, run.thread_id)
  }

  async function openHistory(runId) {
    try {
      setRun(await api(`/runs/${encodeURIComponent(runId)}`))
    } catch (err) {
      setError(err)
    }
  }

  return (
    <main className="page-main search-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>우리 아이 찾기</span>
      </div>
      <div className="page-heading">
        <span className="eyebrow">사진과 설명으로 찾기</span>
        <h1>우리 아이를 알려주세요</h1>
        <p>기억나는 정보를 입력하면 실제 보호소 공고에서 닮은 후보를 찾아 근거와 함께 보여 드려요.</p>
      </div>

      <form className="panel search-form search-form-wide" onSubmit={onSubmit} noValidate>
        <div className="panel-title"><span>01</span><h2>사진과 정보 입력</h2></div>
        <div className="search-form-grid search-form-grid-v2">
          <label className="upload-box">
            사진 올리기
            <input type="file" accept="image/*" onChange={onPhoto} />
            <span>{photo ? '사진을 바꾸려면 다시 선택하세요' : '선택한 사진은 이 화면에서만 보여요'}</span>
            {photo && <img src={photo} alt="올린 반려동물 사진" />}
          </label>
          <div className="search-fields-v2">
            <div className="field-block">
              <span className="field-label">종류 <em className="req">필수</em></span>
              <SpeciesPicker value={form.species} onChange={(species) => setForm((f) => ({ ...f, species }))} />
            </div>
            <label className="search-description">
              특징과 상황
              <textarea rows={5} maxLength={1000} value={form.description} onChange={set('description')} placeholder="털 색, 크기, 성별, 목줄, 눈에 띄는 특징을 적어주세요. 예: 갈색 곱슬털 푸들, 빨간 목줄" />
            </label>
            <div className="form-pair">
              <div className="field-block">
                <span className="field-label">실종 지역 <em className="req">필수</em></span>
                <button type="button" className={`region-trigger${location ? ' filled' : ''}`} onClick={() => setRegionOpen(true)} aria-haspopup="dialog">
                  <span aria-hidden="true">⌖</span>
                  {location
                    ? location.region === '전체' ? '전체 지역' : location.address || location.region
                    : '실종 지역 선택'}
                </button>
              </div>
              <label>
                <span>실종 날짜 <em className="req">필수</em></span>
                <input type="date" value={form.lost_date} max={today()} onChange={set('lost_date')} />
              </label>
            </div>
          </div>
        </div>
        <div className="search-form-bottom">
          <p className="fineprint">
            실종 날짜부터 오늘까지 올라온 공고를 찾아요. 사진은 아직 분석하지 않고, 설명의 털색·품종·특징으로 후보를 정렬해요.
            빈 칸이 있으면 검색 전에 먼저 물어볼게요.
          </p>
          <button className="primary-button" type="submit" disabled={busy}>{busy ? '찾는 중…' : '후보 찾아보기 ↗'}</button>
        </div>
      </form>
      <RegionPicker
        open={regionOpen}
        regions={regions.list}
        initial={location}
        onClose={() => setRegionOpen(false)}
        onSelect={(value) => {
          setLocation(value)
          setRegionOpen(false)
        }}
      />

      <section className="search-results-section" aria-labelledby="results-title">
        <div className="section-head">
          <div>
            <span className="eyebrow">닮은 후보 살펴보기</span>
            <h2 id="results-title">검색 결과 {run?.data_source && <SourceBadge source={run.data_source} />}</h2>
            <p>{run?.scope ? scopeText(run.scope) : '조건을 입력하고 검색하면 최대 10마리의 후보를 보여 드려요.'}</p>
          </div>
        </div>
        <Results run={run} busy={busy} error={error} onWiden={widenRegion} />
      </section>

      <section className="recent-history" aria-labelledby="history-title">
        <div className="section-head">
          <div>
            <span className="eyebrow">다시 찾아보기</span>
            <h2 id="history-title">최근 검색</h2>
          </div>
        </div>
        <div className="history-row">
          {history.length === 0 && <span>아직 검색 기록이 없어요.</span>}
          {history.map((h) => (
            <button type="button" key={h.run_id} onClick={() => openHistory(h.run_id)}>
              {runSummary(h.criteria)}
              <br />
              {runStatusLabel(h.status)} · 후보 {h.candidate_count} · {formatDateTime(h.created_at)}
            </button>
          ))}
        </div>
      </section>
    </main>
  )
}


function Results({ run, busy, error, onWiden }) {
  if (busy) return <p className="state-box">공고를 조회하고 후보를 비교하고 있어요…</p>
  if (error) {
    return (
      <div className="state-box state-error" role="alert">
        <strong>검색하지 못했어요.</strong>
        <p>{errorMessage(error)}</p>
      </div>
    )
  }
  if (!run) return <p className="empty-results">아직 검색하지 않았어요.</p>

  const meta = (
    <p className="run-meta">
      도구 호출 {run.tool_call_count ?? run.tool_calls?.length ?? 0}회 · 판단 수정 {run.reflection_count ?? 0}회 · 통신 재시도 {run.retry_count ?? 0}회
      {run.reflections?.length > 0 && ` · 수정 내용: ${run.reflections.map((r) => r.strategy).join(', ')}`}
    </p>
  )

  if (run.status === 'awaiting_input') {
    const widen = run.questions?.some((q) => q.field === 'region' && run.scope)
    return (
      <div className="panel question-panel" role="status">
        <strong>조금만 더 알려 주세요</strong>
        <ul>{run.questions?.map((q) => <li key={q.field + q.message}>{q.message}</li>)}</ul>
        <p className="fineprint">위 입력란을 채우고 다시 검색하면 앞서 입력한 조건과 합쳐서 이어서 찾아요.</p>
        {widen && <button type="button" className="primary-button" onClick={onWiden}>전체 지역으로 넓혀 찾기</button>}
        {meta}
      </div>
    )
  }

  const candidates = run.candidates || []
  return (
    <>
      {run.error && (
        <div className="state-box state-error" role="alert">
          <strong>{run.status === 'failed' ? '검색에 실패했어요.' : '일부 결과만 보여 드려요.'}</strong>
          <p>{run.error.message}</p>
        </div>
      )}
      {run.status === 'partial' && !run.error && (
        <p className="state-box">검증에서 해결하지 못한 문제가 있어 부분 결과로 표시해요.</p>
      )}
      {run.status !== 'failed' && candidates.length === 0 && (
        <p className="empty-results">
          이 조건에서는 닮은 후보를 찾지 못했어요. 보호 중인 동물이 없다는 뜻은 아니에요. 지역·기간을 바꿔 다시 찾아보세요.
        </p>
      )}
      {candidates.length > 0 && (
        <div className="result-grid">
          {candidates.map((c) => (
            <Link key={c.id} className="result-card" to={`/notices/${encodeURIComponent(c.id)}?run=${run.run_id}`}>
              <NoticePhoto item={c} variant="notice" />
              <span className="result-card-body">
                <span className="sample-label">{c.rank}순위 · 점수 {c.score}</span>
                <strong>{noticeTitle(c)}</strong>
                <small>{c.happen_place || '발견 장소 미확인'} · {formatDate(c.happen_date)}</small>
                <small>{c.evidence?.matched?.length ? c.evidence.matched.join(' · ') : '일치 근거 없음(조건 범위 안의 공고)'}</small>
              </span>
            </Link>
          ))}
        </div>
      )}
      {meta}
    </>
  )
}
