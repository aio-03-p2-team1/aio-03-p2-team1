import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { errorMessage, formatDate, formatDateTime, noticeTitle, runStatusLabel, runSummary, scopeText } from '../lib/format.js'
import { distanceLabel, radiusText, widenRadiusAction } from '../lib/radius.js'
import RadiusMap from '../components/RadiusMap.jsx'
import NoticePhoto from '../components/NoticePhoto.jsx'
import Pagination from '../components/Pagination.jsx'
import { useSearchScroll, useSearchViewState } from '../lib/searchView.jsx'
import { cachedPage, pageNumber, rememberPage } from '../lib/pagination.js'
import PhotoFeedbackPopup from '../components/PhotoFeedbackPopup.jsx'
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
  const [form, setForm] = useSearchViewState('form', initialForm)
  const [location, setLocation] = useSearchViewState('location', null) // { region, address, lat?, lng? }
  const [regionOpen, setRegionOpen] = useState(false)
  const [photo, setPhoto] = useSearchViewState('photo', '')
  const [photoAnalyzing, setPhotoAnalyzing] = useState(false)
  const [photoMessage, setPhotoMessage] = useState('')
  const [photoFeedbackOpen, setPhotoFeedbackOpen] = useState(false)
  const [photoFeedback, setPhotoFeedback] = useState('')
  const photoRequestId = useRef(0)
  const [photoFeatureText, setPhotoFeatureText] = useSearchViewState('photoFeatureText', '')
  const [photoSpecies, setPhotoSpecies] = useSearchViewState('photoSpecies', '')
  const [run, setRun] = useSearchViewState('run', null)
  const [pageCache, setPageCache] = useSearchViewState('pages', {})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])

  const [params, setParams] = useSearchParams()
  const runParam = params.get('run')
  const pageParam = pageNumber(params.get('page'))
  useSearchScroll(`${runParam}:${pageParam}`, !busy && Boolean(run))

  useEffect(() => {
    document.title = '다시 만나 · 우리 아이 찾기'
    loadHistory()
  }, [])

  // 마이페이지 검색 기록에서 들어오면(?run=) 그 결과를 바로 보여 준다.
  useEffect(() => {
    if (!runParam) return
    const key = `${runParam}:${pageParam}`
    const cached = cachedPage(pageCache, key)
    if (cached) {
      setRun(cached)
      setError(null)
      setBusy(false)
      return
    }
    const controller = new AbortController()
    setBusy(true)
    setError(null)
    api(`/runs/${encodeURIComponent(runParam)}?page=${pageParam}`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return
        setRun(result)
        setPageCache((previous) => rememberPage(previous, key, result))
      })
      .catch((err) => { if (err.name !== 'AbortError') setError(err) })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [runParam, pageParam])

  function loadHistory() {
    api('/runs?limit=8').then((body) => setHistory(body.runs)).catch(() => setHistory([]))
  }

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }))

  async function onPhoto(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const requestId = ++photoRequestId.current
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setPhotoFeedbackOpen(false)
      setPhotoAnalyzing(false)
      return setPhotoMessage('JPG, PNG, WEBP 사진을 선택해 주세요.')
    }
    if (file.size > 8 * 1024 * 1024) {
      setPhotoFeedbackOpen(false)
      setPhotoAnalyzing(false)
      return setPhotoMessage('사진은 8MB 이하로 선택해 주세요.')
    }
    const oldAuto = photoFeatureText
    const oldSpecies = photoSpecies
    if (oldAuto || oldSpecies) {
      setForm((current) => ({
        ...current,
        ...(oldSpecies && current.species === oldSpecies ? { species: '' } : {}),
        ...(oldAuto && current.description.startsWith(oldAuto)
          ? { description: current.description.slice(oldAuto.length).trimStart() }
          : {}),
      }))
    }
    setPhotoFeatureText('')
    setPhotoSpecies('')
    setPhoto(URL.createObjectURL(file))
    setPhotoMessage('')
    setPhotoFeedbackOpen(false)
    setPhotoFeedback('')
    setPhotoAnalyzing(true)
    try {
      const encoded = await readAsBase64(file)
      const result = await api('/photo-analysis', { method: 'POST', body: { image_base64: encoded } })
      if (requestId !== photoRequestId.current) return
      if (!result.suitable) {
        setPhotoMessage(result.message || '사진에서 동물을 선명하게 확인하지 못했어요. 동물이 중심에 보이는 사진을 올려 주세요.')
        return
      }
      const traits = [
        result.breed,
        ...result.colors,
        result.sex === 'M' ? '수컷' : result.sex === 'F' ? '암컷' : '',
        ...result.marks,
      ].filter(Boolean)
      const extracted = traits.length ? `사진에서 확인한 특징: ${traits.join(', ')}` : ''
      const hasAutoValues = Boolean(result.species || extracted)
      if (!hasAutoValues) {
        setPhotoMessage('사진은 확인했지만 신뢰도 높은 특징을 찾지 못했어요. 아래 입력란에 직접 적어 주세요.')
        return
      }
      setForm((current) => ({
        ...current,
        ...(result.species ? { species: result.species } : {}),
        ...(extracted ? { description: [extracted, current.description].filter(Boolean).join('\n') } : {}),
      }))
      setPhotoFeatureText(extracted)
      setPhotoSpecies(result.species || '')
      setPhotoFeedbackOpen(true)
    } catch (err) {
      if (requestId === photoRequestId.current) setPhotoMessage(errorMessage(err))
    } finally {
      if (requestId === photoRequestId.current) setPhotoAnalyzing(false)
    }
  }

  async function submit(criteria, threadId) {
    setBusy(true)
    setError(null)
    try {
      const body = { criteria, reflection_enabled: true }
      if (threadId) body.thread_id = threadId
      const result = await api('/searches', { method: 'POST', body })
      setRun(result)
      setPageCache((previous) => rememberPage(previous, `${result.run_id}:1`, result))
      setParams({ run: result.run_id, page: '1' })
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

  // 반경 넓히기: 사용자가 버튼을 눌러 동의한 경우에만 다음 단계로 같은 세션에서 다시 찾는다.
  function widenRadius(step) {
    submit({ radius_step: step }, run.thread_id)
  }

  function openHistory(runId) {
    setParams({ run: runId, page: '1' })
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
          <div className="photo-upload-column">
            <label className="upload-box">
              사진 올리기
              <input type="file" accept="image/jpeg,image/png,image/webp" onChange={onPhoto} />
              <span>{photo ? '사진을 바꾸려면 다시 선택하세요' : '찾을 동물이 중심에 선명하게 보이는 JPG·PNG·WEBP (최대 8MB)'}</span>
              {photo && <img src={photo} alt="올린 반려동물 사진" />}
              {photoAnalyzing && <span className="photo-analyzing">사진 특징을 살펴보고 있어요…</span>}
            </label>
            {photoMessage && <p className="photo-analysis-message" role="status">{photoMessage}</p>}
          </div>
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
            사진을 OpenAI 분석 요청에 보내 보이는 특징을 입력란에 채워요. 이미지는 서비스에 저장하지 않으며, 입력된 내용은 직접 고치거나 다른 사진으로 다시 분석할 수 있어요.
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
      {photoFeedbackOpen && (
        <PhotoFeedbackPopup
          feedback={photoFeedback}
          onFeedback={setPhotoFeedback}
          onClose={() => setPhotoFeedbackOpen(false)}
        />
      )}

      <section className="search-results-section" aria-labelledby="results-title">
        <div className="section-head">
          <div>
            <span className="eyebrow">닮은 후보 살펴보기</span>
            <h2 id="results-title">검색 결과 {run?.data_source && <SourceBadge source={run.data_source} />}</h2>
            <p>{run?.scope ? scopeText(run.scope) : '최대 1,000건을 비교해 상위 300건을 페이지로 보여 드려요.'}</p>
          </div>
        </div>
        <Results run={run} busy={busy} error={error} onWiden={widenRegion} onWidenRadius={widenRadius} />
        {!error && run?.pagination && (
          <Pagination page={run.pagination.page} pages={run.pagination.pages} disabled={busy}
            onChange={(page) => setParams({ run: run.run_id, page: String(page) })} />
        )}
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

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
    reader.onerror = () => reject(new Error('사진을 읽지 못했습니다. 다시 선택해 주세요.'))
    reader.readAsDataURL(file)
  })
}


function Results({ run, busy, error, onWiden, onWidenRadius }) {
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

  const radius = run.radius || run.scope?.radius
  if (run.status === 'awaiting_input') {
    const widen = run.questions?.some((q) => q.field === 'region' && run.scope)
    const widenRadiusStep = widenRadiusAction(run.questions, radius)
    return (
      <>
        <RadiusMap radius={radius} />
        <div className="panel question-panel" role="status">
          <strong>조금만 더 알려 주세요</strong>
          <ul>{run.questions?.map((q) => <li key={q.field + q.message}>{q.message}</li>)}</ul>
          <p className="fineprint">위 입력란을 채우고 다시 검색하면 앞서 입력한 조건과 합쳐서 이어서 찾아요.</p>
          {widenRadiusStep && (
            <button type="button" className="primary-button" onClick={() => onWidenRadius(widenRadiusStep.step)}>
              {widenRadiusStep.label}
            </button>
          )}
          {widen && <button type="button" className="primary-button" onClick={onWiden}>전체 지역으로 넓혀 찾기</button>}
          {meta}
        </div>
      </>
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
      <RadiusMap radius={radius} />
      {radius && <p className="radius-summary">{radiusText(radius)}</p>}
      {run.status !== 'failed' && candidates.length === 0 && (
        <p className="empty-results">
          이 조건에서는 닮은 후보를 찾지 못했어요. 보호 중인 동물이 없다는 뜻은 아니에요. 지역·기간을 바꿔 다시 찾아보세요.
        </p>
      )}
      {candidates.length > 0 && (
        <div className="result-grid">
          {candidates.map((c) => (
            <Link key={c.id} className="result-card" to={`/notices/${encodeURIComponent(c.id)}?run=${run.run_id}&page=${run.pagination?.page || 1}`}>
              <NoticePhoto item={c} variant="notice" />
              <span className="result-card-body">
                <span className="sample-label">{c.rank}순위 · {run.ranking_method === 'rrf' ? `RRF ${c.score.toFixed(5)}` : `점수 ${c.score}`}</span>
                <strong>{noticeTitle(c)}</strong>
                <small>{c.happen_place || '발견 장소 미확인'} · {formatDate(c.happen_date)}{distanceLabel(c) && ` · ${distanceLabel(c)}`}</small>
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
