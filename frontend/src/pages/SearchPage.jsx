import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { loadKinds, withSpecies, withPhotoBreed, breedRequest } from '../lib/kinds.js'
import { errorMessage, formatDate, formatDateTime, noticeTitle, runStatusLabel, runSummary, scopeText } from '../lib/format.js'
import { distanceLabel, kmLabel, previewRadius, radiusText, widenRadiusAction } from '../lib/radius.js'
import NoticePhoto from '../components/NoticePhoto.jsx'
import Pagination from '../components/Pagination.jsx'
import { useSearchScroll, useSearchViewState } from '../lib/searchView.jsx'
import { cachedPage, pageNumber, rememberPage } from '../lib/pagination.js'
import RegionPicker from '../components/RegionPicker.jsx'
import SpeciesPicker from '../components/SpeciesPicker.jsx'
import SourceBadge from '../components/SourceBadge.jsx'
import { useToast } from '../components/Toast.jsx'
import { photoAnalysisError, photoErrorMessage, photoSelectionError, photoTraitLine, unsuitablePhotoMessage } from '../lib/photo.js'
import { useRegions } from './useRegions.js'
import { addAnswer, answerChips, applyAnswers, removeAnswer, visibleRequest } from '../lib/agentRequest.js'
import { takePostSearch } from '../lib/postSearch.js'

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const initialForm = () => ({ breed_code: '', species: '', lost_date: today(), description: '' })
export default function SearchPage() {
  const [kinds, setKinds] = useState([])
  const [kindsError, setKindsError] = useState('')
  const [kindsLoading, setKindsLoading] = useState(false)
  const regions = useRegions()
  const toast = useToast()
  const [form, setForm] = useSearchViewState('form', initialForm)
  useEffect(() => {
    let active = true
    setKinds([])
    setKindsError('')
    if (!form.species || form.species === 'all') {
      setKindsLoading(false)
      return
    }
    setKindsLoading(true)
    loadKinds(form.species).then((rows) => { if (active) setKinds(rows) })
      .catch(() => { if (active) setKindsError('품종 목록을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.') })
      .finally(() => { if (active) setKindsLoading(false) })
    return () => { active = false }
  }, [form.species])
  const [location, setLocation] = useSearchViewState('location', null)
  const [regionOpen, setRegionOpen] = useState(false)
  const [photo, setPhoto] = useSearchViewState('photo', '')
  const [photoAnalyzing, setPhotoAnalyzing] = useState(false)
  const [photoMessage, setPhotoMessage] = useState('')
  const photoRequestId = useRef(0)
  const [photoFeatureText, setPhotoFeatureText] = useSearchViewState('photoFeatureText', '')
  const [photoSpecies, setPhotoSpecies] = useSearchViewState('photoSpecies', '')
  // 서버가 보관한 사진 분석 결과 번호. 검색 때 함께 보내면 서버가 사진 특징·사진 받음 여부를 이 결과로 판단한다
  // (설명 글의 '사진에서 확인한 특징' 줄은 보여 주기용이라, 사용자가 지우거나 고쳐도 판단은 바뀌지 않음).
  const [photoAnalysisId, setPhotoAnalysisId] = useSearchViewState('photoAnalysisId', '')
  const [refinementId, setRefinementId] = useState('')
  const [refining, setRefining] = useState(false)
  const refinementLock = useRef(false)
  const photoSourceRef = useRef(null)
  const [run, setRun] = useSearchViewState('run', null)
  const [pageCache, setPageCache] = useSearchViewState('pages', {})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])
  // 에이전트 요청(사진·추가 정보)에 대한 답. 설명 글을 고치지 않고 칩으로 따로 보관해 검색 조건에 합친다.
  const [answers, setAnswers] = useSearchViewState('answers', {})
  const [declined, setDeclined] = useSearchViewState('declined', []) // '잘 모르겠어요'한 항목(같은 대화에서 다시 묻지 않음)
  const descriptionRef = useRef(null)
  const photoInputRef = useRef(null)

  const [params, setParams] = useSearchParams()
  const runParam = params.get('run')
  const pageParam = pageNumber(params.get('page'))
  useSearchScroll(`${runParam}:${pageParam}`, !busy && Boolean(run))

  useEffect(() => {
    document.title = '다시 만나 · 우리 아이 찾기'
    loadHistory()
  }, [])

  // 실종 정보 게시판의 [이 정보로 구조 공고 찾기]로 들어오면 텍스트·사진을 한 번 정리한 뒤 바로 찾는다.
  useEffect(() => {
    const prefill = takePostSearch()
    if (!prefill) return
    setForm(prefill.form)
    setLocation(prefill.location)
    setRun(null)
    setPageCache({})
    setAnswers({})
    setDeclined([])
    setPhoto('')
    setPhotoFeatureText('')
    setPhotoSpecies('')
    setPhotoAnalysisId('')
    setRefinementId('')
    setParams({}, { replace: true })
    toast(`'${prefill.source?.title || '게시글'}' 정보로 찾고 있어요. 입력을 고쳐 다시 찾을 수도 있어요.`)
    const auto = { baseForm: prefill.form, location: prefill.location }
    if (prefill.photo && prefill.source?.id) {
      photoSourceRef.current = { postId: prefill.source.id }
      setPhoto(prefill.photo)
      refineText({ description: prefill.form.description, source: { postId: prefill.source.id }, autoSearch: auto })
    } else if (prefill.form.description?.trim()) {
      refineText({ description: prefill.form.description, source: null, autoSearch: auto })
    } else {
      submit(buildCriteria(prefill.form, {}, prefill.location), undefined, { photoId: '' })
    }
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

  const set = (key) => (event) => {
    if (key === 'description') setRefinementId('')
    setForm((f) => ({ ...f, [key]: event.target.value }))
  }

  async function onPhoto(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    photoSourceRef.current = { file }
    setRefinementId('')
    await analyzePhoto({ file }, URL.createObjectURL(file))
  }

  async function refineText({ description = form.description, source = photoSourceRef.current, autoSearch = null } = {}) {
    if (refinementLock.current) return
    const original = description.trim()
    if (!original && !source) return toast('다듬을 특징이나 상황을 입력하거나 사진을 올려 주세요.')
    refinementLock.current = true
    setRefining(true)
    setError(null)
    try {
      const body = { description: original }
      if (source?.file) body.image_base64 = await readAsBase64(source.file)
      else if (source?.postId) body.post_id = source.postId
      const result = await api('/searches/refine', { method: 'POST', body })
      const nextForm = { ...(autoSearch?.baseForm || form), description: result.description }
      setForm((current) => ({ ...current, description: result.description }))
      setRefinementId(result.refinement_id)
      if (autoSearch) {
        submit(buildCriteria(nextForm, {}, autoSearch.location), undefined, {
          photoId: '', refinementId: result.refinement_id,
          extraDeclined: source && !result.photo_used ? ['photo'] : [],
        })
      } else {
        toast('특징과 상황을 템플릿으로 정리했어요. 내용을 확인한 뒤 찾아보세요.')
      }
    } catch (err) {
      setError(err)
      toast(errorMessage(err))
      if (autoSearch) {
        // 다듬기 호출 자체가 실패한 경우에도 원문으로 검색은 이어 간다.
        submit(buildCriteria(autoSearch.baseForm, {}, autoSearch.location), undefined,
          { photoId: '', extraDeclined: source ? ['photo'] : [] })
      }
    } finally {
      refinementLock.current = false
      setRefining(false)
    }
  }

  // 사진 한 장을 보여 주고 특징을 분석해 입력에 채운다. 직접 올린 사진과 게시글 사진이 같은 흐름을 쓴다.
  // source: { file } 직접 올린 사진 | { postId } 게시글 사진(서버가 게시글에서 사진을 꺼내 분석. 분실 신고 사진은
  //         공공데이터 서버 주소라 브라우저가 읽지 못해서 서버가 대신 받는다).
  // previewUrl: 화면에 보여 줄 주소. fresh: 게시글로 새로 채운 직후라 이전 사진 특징을 지울 필요가 없음.
  // autoSearch: { baseForm, location } 이면 분석이 끝난 뒤(실패해도) 그 입력에 사진 특징을 더해 바로 찾는다.
  async function analyzePhoto(source, previewUrl, { fresh = false, autoSearch = null } = {}) {
    const { file, postId } = source
    const requestId = ++photoRequestId.current
    let searchForm = autoSearch?.baseForm || null
    const selectionError = file ? photoSelectionError(file) : null
    if (selectionError) {
      setPhotoAnalyzing(false)
      return setPhotoMessage(photoErrorMessage(selectionError))
    }
    const oldAuto = fresh ? '' : photoFeatureText
    const photoAsked = visibleRequest(run, answers, declined)?.type === 'photo'
    const oldSpecies = fresh ? '' : photoSpecies
    if (oldAuto || oldSpecies) {
      setForm((current) => ({
        ...current,
        ...(oldSpecies && current.species === oldSpecies ? { species: '', breed_code: '' } : {}),
        ...(oldAuto && current.description.startsWith(oldAuto)
          ? { description: current.description.slice(oldAuto.length).trimStart() }
          : {}),
      }))
    }
    setPhotoFeatureText('')
    setPhotoSpecies('')
    setPhotoAnalysisId('')
    let analysisId = ''
    setPhoto(previewUrl)
    setPhotoMessage('')
    setPhotoAnalyzing(true)
    try {
      const body = file ? { image_base64: await readAsBase64(file) } : { post_id: postId }
      const result = await api('/photo-analysis', { method: 'POST', body })
      if (requestId !== photoRequestId.current) return
      // 쓸 수 없는 사진이어도 번호는 보낸다(서버가 '받았지만 쓸 수 없음'으로 보고 더 나은 사진을 요청할 수 있게).
      analysisId = result.analysis_id || ''
      setPhotoAnalysisId(analysisId)
      const unsuitableMessage = unsuitablePhotoMessage(result)
      if (unsuitableMessage) {
        setPhotoMessage(unsuitableMessage)
        return
      }
      const traits = [
        ...result.colors,
        result.sex === 'M' ? '수컷' : result.sex === 'F' ? '암컷' : '',
        ...result.marks,
      ].filter(Boolean)
      // 설명 글에 이미 있는 특징(예: 털색: 흰색, 빨간 목줄)은 빼고 새로 확인한 것만 붙인다.
      // 비교할 글에서는 이전 사진 줄(oldAuto)을 빼고 본다(사진을 바꿔 올렸을 때 이전 사진 특징과 비교하지 않게).
      const written = (searchForm || form).description || ''
      const extracted = photoTraitLine(traits, oldAuto && written.startsWith(oldAuto) ? written.slice(oldAuto.length) : written)
      const hasAutoValues = Boolean(result.species || extracted)
      if (!hasAutoValues) {
        setPhotoMessage('사진은 확인했지만 신뢰도 높은 특징을 찾지 못했어요. 아래 입력란에 직접 적어 주세요.')
        return
      }
      setForm((current) => ({
        ...current,
        ...withPhotoBreed(current, result),
        ...(extracted ? { description: [extracted, current.description].filter(Boolean).join('\n') } : {}),
      }))
      if (searchForm) {
        searchForm = {
          ...searchForm,
          ...withPhotoBreed(searchForm, result),
          ...(extracted ? { description: [extracted, searchForm.description].filter(Boolean).join('\n') } : {}),
        }
      }
      setPhotoFeatureText(extracted)
      setPhotoSpecies(result.species || '')
      // 에이전트가 사진을 요청한 상태였다면, 사진 특징을 넣어 같은 대화로 바로 다시 찾는다(다시 임베딩·정렬).
      if (photoAsked && extracted) {
        const base = oldAuto && form.description.startsWith(oldAuto) ? form.description.slice(oldAuto.length).trimStart() : form.description
        const nextForm = {
          ...form,
          ...withPhotoBreed(form, result),
          description: [extracted, base].filter(Boolean).join('\n'),
        }
        submit(buildCriteria(nextForm, answers), run.thread_id, { photoId: analysisId })
      }
    } catch (err) {
      if (requestId === photoRequestId.current) setPhotoMessage(photoErrorMessage(photoAnalysisError(err)))
    } finally {
      if (requestId === photoRequestId.current) {
        setPhotoAnalyzing(false)
        // 게시글로 들어온 경우: 사진 분석이 실패해도 글 정보만으로 찾는다.
        // 게시글 사진을 이미 보여 줬으므로, 분석이 실패해(번호 없음) 사진을 다시 요청하는 일은 막는다.
        if (searchForm) {
          submit(buildCriteria(searchForm, {}, autoSearch.location), undefined,
            { photoId: analysisId, extraDeclined: analysisId ? [] : ['photo'] })
        }
      }
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
  const agentRequest = visibleRequest(run, answers, declined)
  const chips = answerChips(answers)

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

  // photoId: 사진 분석 번호(기본은 지금 화면의 번호. 분석 직후처럼 상태가 아직 반영되지 않았으면 직접 넘긴다).
  // extraDeclined: 이번 검색에서 다시 묻지 않을 항목.
  async function submit(criteria, threadId, { photoId = photoAnalysisId, refinementId: refinedId = refinementId, extraDeclined = [] } = {}) {
    setBusy(true)
    setError(null)
    try {
      const body = { criteria, reflection_enabled: true }
      if (threadId) body.thread_id = threadId
      // 같은 대화면 '모르겠어요' 항목을 함께 보내 다시 묻지 않게 한다. 새 대화면 초기화.
      if (photoId) body.photo_analysis_id = photoId
      if (refinedId) body.refinement_id = refinedId
      const skip = [...new Set([...(threadId ? declined : []), ...extraDeclined])]
      if (skip.length) body.declined = skip
      if (!threadId) setDeclined(extraDeclined)
      const result = await api('/searches', { method: 'POST', body })
      setRun(result)
      setPageCache((previous) => rememberPage(previous, `${result.run_id}:1`, result))
      setParams({ run: result.run_id, page: '1' })
      loadHistory()
      // 무엇이 필요한지 알 수 있게 첫 질문을 그대로 보여 준다(예: 지역을 넓혀 볼까요?)
      if (result.status === 'awaiting_input') toast(result.questions?.[0]?.message || '추가 정보가 필요해요.')
      // 결과는 보여 주되, 에이전트가 사진·정보를 요청했으면 알림으로도 알려 준다(카드는 입력란 위에 있음).
      else if (result.agent_request) toast(`${result.agent_request.reason} 입력란 위에서 골라 주세요.`)
      scrollToResults()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  // loc: 실종 위치. 기본은 지금 화면의 위치, 게시글로 막 채운 직후처럼 상태가 아직 반영되지 않았으면 직접 넘긴다.
  function buildCriteria(values, answerValues, loc = location) {
    const criteria = breedRequest(values)
    for (const [k, v] of Object.entries(values)) if (k !== 'breed' && v.trim()) criteria[k] = v.trim()
    if (loc?.region) criteria.region = loc.region
    if (loc?.address) criteria.lost_place = loc.address
    // 지도에서 찍은 점을 반경 중심으로 보낸다(서버가 한국 범위 검사). 미리 보기와 실제 검색 범위가 같아진다.
    if (loc?.address && Number.isFinite(loc?.lat) && Number.isFinite(loc?.lng)) {
      criteria.lost_lat = Number(loc.lat.toFixed(6))
      criteria.lost_lng = Number(loc.lng.toFixed(6))
    }
    return applyAnswers(criteria, answerValues)
  }

  function onSubmit(event) {
    event.preventDefault()
    if (busy || refining) return
    // 질문에 답하는 중이거나 에이전트 요청이 있던 검색이면 같은 대화로 이어서 찾는다.
    const followUp = run?.status === 'awaiting_input' || run?.agent_request
    submit(buildCriteria(form, answers), followUp ? run.thread_id : undefined)
  }

  // 요청 카드의 보기를 고르면 칩으로 남기고 같은 대화로 바로 다시 찾는다.
  function chooseAnswer(field, value) {
    const next = addAnswer(answers, field, value)
    setAnswers(next)
    submit(buildCriteria(form, next), run.thread_id)
  }

  function declineRequest(key) {
    setDeclined((current) => (current.includes(key) ? current : [...current, key]))
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
    scrollToResults()
  }

  function openPage(page) {
    setParams({ run: run.run_id, page: String(page) })
    scrollToResults()
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
        <fieldset className="search-form-grid search-form-grid-v2" disabled={refining}>
          <div className="photo-upload-column">
            <label className="upload-box">
              사진 올리기
              <input ref={photoInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={onPhoto} />
            <span>{photo ? '사진을 바꾸려면 다시 선택하세요' : '찾을 동물이 중심에 선명하게 보이는 사진 (JPG, PNG 또는 WEBP · 최대 8MB)'}</span>
              {photo && <img src={photo} alt="올린 반려동물 사진" referrerPolicy="no-referrer" />}
              {photoAnalyzing && <span className="photo-analyzing">사진 특징을 살펴보고 있어요…</span>}
            </label>
            {photoMessage && <p className="photo-analysis-message" role="status">{photoMessage}</p>}
          </div>
          <div className="search-fields-v2">
            <div className="field-block">
              <span className="field-label">종류 <em className="req">필수</em></span>
              <SpeciesPicker value={form.species} onChange={(species) => setForm((f) => withSpecies(f, species))} />
              <label>품종 (선택)
                <select aria-label="품종" value={form.breed_code || ''} onChange={set('breed_code')}
                  disabled={!form.species || form.species === 'all' || kindsLoading || !kinds.length}>
                  <option value="">{kindsLoading ? '품종 불러오는 중…' : '품종을 선택해 주세요'}</option>
                  {kinds.map((kind) => <option key={kind.kind_code} value={kind.kind_code}>{kind.name}</option>)}
                </select>
              </label>
              {kindsError && <p role="alert">{kindsError}</p>}
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
            {agentRequest && (
              <div className="agent-request" role="status" aria-live="polite" id="agent-request">
                <p className="agent-request-reason"><strong>{agentRequest.type === 'photo' ? '사진 요청' : `${agentRequest.label} 확인`}</strong> {agentRequest.reason}</p>
                <div className="agent-request-actions">
                  {agentRequest.type === 'info' && agentRequest.options.map((option) => (
                    <button key={option} type="button" className="secondary-button" disabled={busy} onClick={() => chooseAnswer(agentRequest.field, option)}>{option}</button>
                  ))}
                  {agentRequest.type === 'photo' && (
                    <button type="button" className="secondary-button" disabled={busy || photoAnalyzing} onClick={() => photoInputRef.current?.click()}>사진 올리기</button>
                  )}
                  <button type="button" className="text-button" onClick={() => descriptionRef.current?.focus()}>직접 적을게요</button>
                  <button type="button" className="text-button" onClick={() => declineRequest(agentRequest.type === 'photo' ? 'photo' : agentRequest.field)}>잘 모르겠어요</button>
                </div>
              </div>
            )}
            <div className="search-description">
              <div className="search-description-head">
                <label htmlFor="search-description-input">특징과 상황</label>
                <button type="button" className="refine-button" disabled={refining || busy}
                  onClick={() => refineText()} aria-label="텍스트 다듬기">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 4 5 5M13.5 5.5l5 5L9 20H4v-5L13.5 5.5ZM4 3v4M2 5h4M18 14v6M15 17h6" /></svg>
                  {refining ? '다듬는 중…' : '텍스트 다듬기'}
                </button>
              </div>
              <div className={`description-wrap${refining ? ' is-refining' : ''}`}>
                <textarea id="search-description-input" ref={descriptionRef} rows={5} maxLength={1000}
                  value={form.description} onChange={set('description')} disabled={refining}
                  aria-describedby={questionNotes.length ? 'form-questions' : undefined}
                  placeholder="털 색, 크기, 성별, 목줄, 눈에 띄는 특징을 적어주세요. 예: 갈색 곱슬털, 빨간 목줄. 품종은 위 목록에서 선택해 주세요." />
                {refining && <span className="refine-shimmer" aria-hidden="true" />}
              </div>
            </div>
            {chips.length > 0 && (
              <div className="answer-chips" aria-label="요청에 답한 값">
                {chips.map((chip) => (
                  <button key={chip.label} type="button" className="answer-chip" onClick={() => setAnswers(removeAnswer(answers, chip.field, chip.value))} aria-label={`${chip.label} 지우기`}>
                    {chip.label} <span aria-hidden="true">✕</span>
                  </button>
                ))}
              </div>
            )}
            {/* 실종 날짜는 실종 지역 선택 창 안에서 함께 고른다(위치·날짜·검색 범위를 한 화면에서). */}
            <div className="field-block">
              <span className="field-label">실종 지역 · 날짜 <em className="req">필수</em></span>
              <button type="button" className={`region-trigger${location ? ' filled' : ''}`} onClick={() => setRegionOpen(true)} aria-haspopup="dialog">
                <span aria-hidden="true">⌖</span>
                {locationSummary}
              </button>
            </div>
          </div>
        </fieldset>
        <div className="search-form-bottom">
          <p className="fineprint">
            사진을 살펴보고 확인된 특징을 입력란에 적어드려요. 사진은 저장하지 않으며, 입력된 특징은 직접 고칠 수 있어요.
            빈 칸이 있으면 검색 전에 먼저 물어볼게요.
          </p>
          <button className="primary-button" type="submit" disabled={busy || refining}>{busy ? '찾는 중…' : '후보 찾아보기'}</button>
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
            onChange={openPage} />
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

function scrollToResults() {
  document.getElementById('results-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
