import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { errorMessage, formatDate, formatDateTime, noticeTitle, runStatusLabel, runSummary, scopeText } from '../lib/format.js'
import { distanceLabel, kmLabel, previewRadius, radiusText, widenRadiusAction } from '../lib/radius.js'
import NoticePhoto from '../components/NoticePhoto.jsx'
import Pagination from '../components/Pagination.jsx'
import { useSearchScroll, useSearchViewState } from '../lib/searchView.jsx'
import { cachedPage, pageNumber, rememberPage } from '../lib/pagination.js'
import PhotoFeedbackPopup from '../components/PhotoFeedbackPopup.jsx'
import RegionPicker from '../components/RegionPicker.jsx'
import SpeciesPicker from '../components/SpeciesPicker.jsx'
import SourceBadge from '../components/SourceBadge.jsx'
import { useToast } from '../components/Toast.jsx'
import { photoAnalysisError, photoErrorMessage, photoSelectionError, unsuitablePhotoMessage } from '../lib/photo.js'
import { useRegions } from './useRegions.js'

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const initialForm = () => ({ species: '', lost_date: today(), description: '' })
export default function SearchPage() {
  const regions = useRegions()
  const toast = useToast()
  const [form, setForm] = useSearchViewState('form', initialForm)
  const [location, setLocation] = useSearchViewState('location', null)
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
    const selectionError = photoSelectionError(file)
    if (selectionError) {
      setPhotoFeedbackOpen(false)
      setPhotoAnalyzing(false)
      return setPhotoMessage(photoErrorMessage(selectionError))
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
      const unsuitableMessage = unsuitablePhotoMessage(result)
      if (unsuitableMessage) {
        setPhotoMessage(unsuitableMessage)
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
      if (requestId === photoRequestId.current) setPhotoMessage(photoErrorMessage(photoAnalysisError(err)))
    } finally {
      if (requestId === photoRequestId.current) setPhotoAnalyzing(false)
    }
  }

  // 입력 카드에 보여 줄 추가 질문. 범위 넓히기(radius, 결과가 있는 상태의 region)는 권하는 질문, 나머지는 답해야 하는 질문.
  const pending = run?.status === 'awaiting_input' ? run.questions || [] : []
  const questionNotes = pending.map((q) => ({
    ...q,
    blocking: !(q.field === 'radius' || (q.field === 'region' && run?.scope)),
  }))
  const widenStep = run?.status === 'awaiting_input' ? widenRadiusAction(run.questions, run.radius || run.scope?.radius) : null
  const canWidenRegion = pending.some((q) => q.field === 'region' && run?.scope)

  // 실종 지역 버튼에 보여 줄 요약(위치 · 실종 날짜 · 반경). 반경은 검색과 같은 기준표로 계산한다.
  const preview = previewRadius(location, form.lost_date, today())
  // 넓히기를 눌러 검색한 뒤에는 실제로 찾은 반경(서버 값)을 요약에 보여 준다.
  // 단, 그 검색과 위치·실종 날짜가 같을 때만. 위치나 날짜를 바꿨으면 새 날짜 기준 반경을 보여 준다
  // (서버도 위치·날짜가 바뀌면 넓히기 단계를 잇지 않는다).
  const searched = run?.radius || run?.scope?.radius
  const sameSearch = searched?.auto === false && searched.lost_place === location?.address
    && run?.criteria?.lost_date === form.lost_date
  const shownKm = sameSearch ? searched.radius_km : preview?.radius_km
  const locationSummary = !location
    ? '실종 지역과 날짜 선택'
    : [
        location.region === '전체' ? '전체 지역' : location.address || location.region,
        form.lost_date && `${form.lost_date.slice(5).replace('-', '.')} 실종`,
        preview && (shownKm != null ? kmLabel(shownKm) : '조회 지역 전체'),
      ].filter(Boolean).join(' · ')

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
      // 무엇이 필요한지 알 수 있게 첫 질문을 그대로 보여 준다(예: 지역을 넓혀 볼까요?)
      if (result.status === 'awaiting_input') toast(result.questions?.[0]?.message || '추가 정보가 필요해요.')
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
    // 지도에서 찍은 점을 반경 중심으로 보낸다(서버가 한국 범위 검사). 미리 보기와 실제 검색 범위가 같아진다.
    if (location?.address && Number.isFinite(location?.lat) && Number.isFinite(location?.lng)) {
      criteria.lost_lat = Number(location.lat.toFixed(6))
      criteria.lost_lng = Number(location.lng.toFixed(6))
    }
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
        <p>반려동물의 정보와 실종 지역을 입력하면 비슷한 공고를 찾아드려요.</p>
      </div>

      <form className="panel search-form search-form-wide" onSubmit={onSubmit} noValidate>
        <div className="panel-title"><span>01</span><h2>사진과 정보 입력</h2></div>
        <div className="search-form-grid search-form-grid-v2">
          <div className="photo-upload-column">
            <label className="upload-box">
              사진 올리기
              <input type="file" accept="image/jpeg,image/png,image/webp" onChange={onPhoto} />
            <span>{photo ? '사진을 바꾸려면 다시 선택하세요' : '찾을 동물이 중심에 선명하게 보이는 사진 (JPG, PNG 또는 WEBP · 최대 8MB)'}</span>
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
            {/* 추가 질문을 입력 카드 안에도 보여 준다. 답해야 하는 질문(빈 칸·입력 오류)은 빨간색,
                범위를 넓힐지 묻는 질문은 금색으로 구분하고, 넓히기 버튼을 바로 옆에 둔다. */}
            {questionNotes.length > 0 && (
              <div className="form-questions" role="status" aria-live="polite" id="form-questions">
                {questionNotes.map((q) => (
                  <p key={q.field + q.message} className={q.blocking ? 'form-question blocking' : 'form-question'}>
                    <strong>{q.blocking ? '확인 필요' : '범위 넓히기'}</strong> {q.message}
                  </p>
                ))}
                {(widenStep || canWidenRegion) && (
                  <div className="form-question-actions">
                    {widenStep && (
                      <button type="button" className="secondary-button" disabled={busy} onClick={() => widenRadius(widenStep.step)}>
                        {widenStep.label}
                      </button>
                    )}
                    {canWidenRegion && (
                      <button type="button" className="secondary-button" disabled={busy} onClick={widenRegion}>전체 지역으로 넓혀 찾기</button>
                    )}
                  </div>
                )}
              </div>
            )}
            <label className="search-description">
              특징과 상황
              <textarea rows={5} maxLength={1000} value={form.description} onChange={set('description')} aria-describedby={questionNotes.length ? 'form-questions' : undefined} placeholder="털 색, 크기, 성별, 목줄, 눈에 띄는 특징을 적어주세요. 예: 갈색 곱슬털 푸들, 빨간 목줄" />
            </label>
            {/* 실종 날짜는 실종 지역 선택 창 안에서 함께 고른다(위치·날짜·검색 범위를 한 화면에서). */}
            <div className="field-block">
              <span className="field-label">실종 지역 · 날짜 <em className="req">필수</em></span>
              <button type="button" className={`region-trigger${location ? ' filled' : ''}`} onClick={() => setRegionOpen(true)} aria-haspopup="dialog">
                <span aria-hidden="true">⌖</span>
                {locationSummary}
              </button>
            </div>
          </div>
        </div>
        <div className="search-form-bottom">
          <p className="fineprint">
            사진을 살펴보고 확인된 특징을 입력란에 적어드려요. 사진은 저장하지 않으며, 입력된 특징은 직접 고칠 수 있어요.
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
        withRadius
        lostDate={form.lost_date}
        onSelect={({ lost_date: lostDate, ...value }) => {
          setLocation(value)
          if (lostDate) setForm((f) => ({ ...f, lost_date: lostDate }))
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
            {run?.scope && <p>{scopeText(run.scope)}</p>}
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
              {runStatusLabel(h.status)} · 비슷한 공고 {h.candidate_count}건 · {formatDateTime(h.created_at)}
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

  const radius = run.radius || run.scope?.radius
  if (run.status === 'awaiting_input') {
    const widen = run.questions?.some((q) => q.field === 'region' && run.scope)
    const widenRadiusStep = widenRadiusAction(run.questions, radius)
    return (
      <>
        <div className="panel question-panel" role="status">
          <strong>조금만 더 알려 주세요</strong>
          <ul>{run.questions?.map((q) => <li key={q.field + q.message}>{q.message}</li>)}</ul>
          <p className="fineprint">위 입력란에 내용을 추가한 뒤 다시 검색해 주세요.</p>
          {widenRadiusStep && (
            <button type="button" className="primary-button" onClick={() => onWidenRadius(widenRadiusStep.step)}>
              {widenRadiusStep.label}
            </button>
          )}
          {widen && <button type="button" className="primary-button" onClick={onWiden}>전체 지역으로 넓혀 찾기</button>}
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
        <p className="state-box">일부 결과만 확인했어요. 조건을 바꿔 다시 검색해 주세요.</p>
      )}
      {/* 검색 범위 지도는 실종 지역 선택 창 하나로 통일하고, 결과 위에는 한 줄 요약만 둔다. */}
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
                <span className="sample-label">{c.rank}순위</span>
                <strong>{noticeTitle(c)}</strong>
                <small>{c.happen_place || '발견 장소 미확인'} · {formatDate(c.happen_date)}{distanceLabel(c) && ` · ${distanceLabel(c)}`}</small>
                <small>{c.evidence?.matched?.length ? c.evidence.matched.join(' · ') : '확인된 특징이 없어요. 공고 내용을 살펴봐 주세요.'}</small>
              </span>
            </Link>
          ))}
        </div>
      )}
    </>
  )
}
