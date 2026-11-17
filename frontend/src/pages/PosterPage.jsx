import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Stage, Layer, Rect, Transformer } from 'react-konva'
import { CanvasItem } from '../components/PosterCanvasItem.jsx'
import { API_BASE, api } from '../lib/api.js'
import { createPosterFromTemplate, POSTER_FIELDS, posterPayload, switchPosterTemplate } from '../lib/posterDocument.js'
import { applyPosterDraft, clearPosterDraft, peekPosterDraft } from '../lib/postPoster.js'
import { textOverflows } from '../lib/posterText.js'
import { usePosterStore } from '../lib/posterStore.js'

const makeId = () => crypto.randomUUID().replaceAll('-', '')

function ComponentCanvas({ poster, selectedId, zoom, select, update, stageRef }) {
  const transformRef = useRef(null)
  const nodes = useRef({})
  const sorted = useMemo(() => [...poster.components].sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0)), [poster.components])
  useEffect(() => {
    const node = nodes.current[selectedId]
    if (node && transformRef.current) {
      transformRef.current.nodes([node])
      transformRef.current.getLayer()?.batchDraw()
    } else if (transformRef.current) transformRef.current.nodes([])
  }, [selectedId, poster.components])
  return <div className="poster-stage-wrap">
    <div className="poster-stage-viewport" style={{ width: poster.width * zoom, height: poster.height * zoom }}>
    <div className="poster-stage-scale" style={{ width: poster.width, height: poster.height, transform: `scale(${zoom})` }}>
    <Stage ref={stageRef} width={poster.width} height={poster.height}
      onMouseDown={(event) => { if (event.target === event.target.getStage()) select(null) }}
      onTouchStart={(event) => { if (event.target === event.target.getStage()) select(null) }}>
      <Layer>
        <Rect x={0} y={0} width={poster.width} height={poster.height} fill="#FFFFFF" shadowColor="#342e23" shadowBlur={12} shadowOpacity={0.12} onMouseDown={() => select(null)} onTouchStart={() => select(null)} />
        {sorted.map((item) => <CanvasItem key={item.id} item={item} selected={selectedId === item.id} onSelect={() => select(item.id)} onChange={(patch) => update(item.id, patch)} registerNode={(node) => { if (node) nodes.current[item.id] = node; else delete nodes.current[item.id] }} />)}
        <Transformer ref={transformRef} rotateEnabled anchorSize={9} borderStroke="#4c7757" anchorStroke="#4c7757" anchorFill="#fff" />
      </Layer>
    </Stage>
    </div>
    </div>
  </div>
}

export default function PosterPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const poster = usePosterStore((state) => state.poster)
  const selectedId = usePosterStore((state) => state.selectedId)
  const zoom = usePosterStore((state) => state.zoom)
  const setPoster = usePosterStore((state) => state.setPoster)
  const select = usePosterStore((state) => state.select)
  const update = usePosterStore((state) => state.updateComponent)
  const addComponent = usePosterStore((state) => state.addComponent)
  const removeComponent = usePosterStore((state) => state.removeComponent)
  const reorder = usePosterStore((state) => state.reorder)
  const undo = usePosterStore((state) => state.undo)
  const redo = usePosterStore((state) => state.redo)
  const setZoom = usePosterStore((state) => state.setZoom)
  const past = usePosterStore((state) => state.past)
  const future = usePosterStore((state) => state.future)
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef(null)
  const stageRef = useRef(null)
  const posterId = new URLSearchParams(location.search).get('edit')
  const selected = poster?.components.find((item) => item.id === selectedId)

  useEffect(() => {
    let live = true
    Promise.all([api('/poster/templates'), posterId ? api(`/posters/${posterId}`) : Promise.resolve(null)])
      .then(([list, existing]) => {
        if (!live) return
        setTemplates(list.items)
        if (existing) setPoster(existing)
        // 게시판 상세의 [전단지 만들기]로 왔으면 기본 템플릿에 게시글 문구·사진을 채운다(저장은 사용자가 한다).
        const draft = peekPosterDraft()
        const templateId = draft ? 'basic' : list.items[0]?.id || 'basic'
        return api(`/poster/templates/${templateId}`).then((template) => {
          if (!live) return
          const fresh = createPosterFromTemplate(template)
          setPoster(draft ? applyPosterDraft(fresh, draft) : fresh)
          if (draft) {
            clearPosterDraft()
            setNotice('게시글 정보로 전단지를 채웠어요. 연락처를 넣고 저장해 주세요.')
          }
        })
      })
      .catch((error) => live && setNotice(error.message || '전단지 편집기를 불러오지 못했습니다.'))
      .finally(() => live && setLoading(false))
    return () => { live = false }
  }, [posterId, setPoster])

  async function changeTemplate(id) {
    if (!poster || id === poster.templateId) return
    if (!window.confirm('템플릿을 바꾸면 자유 배치와 디자인이 새 템플릿으로 바뀝니다. 입력한 문구와 사진은 유지할까요?')) return
    try {
      const [template] = await Promise.all([api(`/poster/templates/${id}`)])
      const next = switchPosterTemplate(poster, template)
      setPoster(next); setSaved(false); setNotice('템플릿을 바꿨어요. 입력한 문구와 사진은 유지했습니다.')
    } catch (error) { setNotice(error.message) }
  }

  function addText() {
    const component = { id: makeId(), type: 'text', label: '새 텍스트', fieldKey: `custom_${makeId()}`, content: '텍스트를 입력하세요', x: 120, y: 280, width: 500, height: 70, fontSize: 30, color: '#34302b', zIndex: Math.max(0, ...poster.components.map((item) => item.zIndex || 0)) + 1 }
    addComponent(component); setSaved(false)
  }

  function addShape() {
    const component = { id: makeId(), type: 'shape', label: '도형', x: 150, y: 350, width: 320, height: 120, fill: '#e8d8b5', stroke: '#9c8250', opacity: 1, zIndex: Math.max(0, ...poster.components.map((item) => item.zIndex || 0)) + 1 }
    addComponent(component); setSaved(false)
  }

  function addPhotoSlot() {
    const component = { id: makeId(), type: 'image', label: '반려동물 사진', assetId: null, x: 150, y: 260, width: 480, height: 360, opacity: 1, zIndex: Math.max(0, ...poster.components.map((item) => item.zIndex || 0)) + 1 }
    addComponent(component); fileRef.current?.click(); setSaved(false)
  }

  async function uploadFile(file) {
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { setNotice('JPG, PNG, WebP 사진만 올릴 수 있어요.'); return }
    if (file.size > 15 * 1024 * 1024) { setNotice('사진은 15MB 이하로 올려 주세요.'); return }
    let target = selected
    if (!target || target.type !== 'image') {
      target = { id: makeId(), type: 'image', label: '반려동물 사진', assetId: null, x: 150, y: 260, width: 480, height: 360, opacity: 1, zIndex: Math.max(0, ...poster.components.map((item) => item.zIndex || 0)) + 1 }
      addComponent(target)
    }
    try {
      const body = new FormData(); body.append('file', file)
      const response = await fetch(`${API_BASE}/poster/assets`, { method: 'POST', credentials: 'include', body })
      const data = await response.json()
      if (!response.ok) throw new Error(data?.detail?.message || '사진 업로드를 처리하지 못했습니다.')
      update(target.id, { assetId: data.assetId, label: target.label || '반려동물 사진' })
      setNotice('사진을 업로드하고 미리보기용으로 최적화했어요.'); setSaved(false)
    } catch (error) { setNotice(error.message) }
  }

  async function save() {
    if (!poster) return
    setSaving(true); setNotice('')
    try {
      const data = posterId
        ? await api(`/posters/${posterId}`, { method: 'PUT', body: posterPayload(poster) })
        : await api('/posters', { method: 'POST', body: posterPayload(poster) })
      setSaved(true); setNotice('저장되었습니다.')
      // 저장 후에도 편집기에 머문다. 새 전단지는 다음 저장이 수정(PUT)이 되도록 주소만 바꾼다.
      if (!posterId) navigate(`/poster?edit=${data.id}`, { replace: true })
    } catch (error) { setNotice(error.message) } finally { setSaving(false) }
  }

  function downloadPng() {
    const stageInstance = stageRef.current
    if (!stageInstance) { setNotice('PNG를 만들지 못했습니다.'); return }
    const link = document.createElement('a')
    link.download = '실종동물-전단지.png'
    const transformer = stageInstance.findOne('Transformer')
    transformer?.hide()
    link.href = stageInstance.toDataURL({ pixelRatio: 2, mimeType: 'image/png' })
    transformer?.show()
    link.click()
  }

  function printPdf() {
    const stageInstance = stageRef.current
    if (!stageInstance) { setNotice('인쇄용 이미지를 만들지 못했습니다.'); return }
    const printWindow = window.open('', '_blank')
    if (!printWindow) { setNotice('새 창이 차단됐어요. 팝업을 허용한 뒤 다시 시도해 주세요.'); return }
    const transformer = stageInstance.findOne('Transformer')
    transformer?.hide()
    const imageUrl = stageInstance.toDataURL({ pixelRatio: 2, mimeType: 'image/png' })
    transformer?.show()
    printWindow.document.open()
    printWindow.document.write(`<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>실종동물 전단지</title><style>@page{size:A4 portrait;margin:0}html,body{margin:0;width:210mm;height:297mm}img{display:block;width:210mm;height:297mm}</style></head><body><img alt="실종동물 전단지" src="${imageUrl}"></body></html>`)
    printWindow.document.close()
    const image = printWindow.document.querySelector('img')
    let printed = false
    const printWhenReady = () => {
      if (printed) return
      printed = true
      printWindow.focus(); printWindow.print(); printWindow.close()
    }
    image.addEventListener('load', printWhenReady, { once: true })
    image.addEventListener('error', () => { printWindow.close(); setNotice('인쇄용 전단지를 준비하지 못했습니다.') }, { once: true })
    if (image.complete && image.naturalWidth) printWhenReady()
  }

  if (loading) return <main className="page-main"><p className="state-box">전단지 편집기를 준비하고 있어요…</p></main>
  if (!poster) return <main className="page-main"><p className="state-box state-error">{notice || '전단지를 불러오지 못했습니다.'}</p></main>
  const textComponents = poster.components.filter((item) => item.type === 'text').sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0))
  return <main className="poster-page">
    <div className="poster-topbar">
      <div><span className="eyebrow">MISSING PET POSTER</span><h1>실종 전단지 만들기</h1></div>
      <div className="poster-top-actions">
        <label className="poster-select-label">템플릿<select value={poster.templateId} onChange={(event) => changeTemplate(event.target.value)}>{templates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <button className="secondary-button" type="button" onClick={undo} disabled={!past.length}>실행 취소</button>
        <button className="secondary-button" type="button" onClick={redo} disabled={!future.length}>다시 실행</button>
        <button className="secondary-button" type="button" onClick={downloadPng}>PNG 다운로드</button>
        <button className="secondary-button" type="button" onClick={printPdf}>PDF / 인쇄</button>
        <button className="primary-button" type="button" onClick={save} disabled={saving}>{saving ? '저장 중…' : saved ? '저장 완료' : '저장'}</button>
      </div>
    </div>
    <div className="poster-workspace">
      <section className="poster-canvas-panel panel" aria-label="전단지 캔버스">
        <div className="poster-canvas-toolbar">
          <div className="poster-add-actions"><button type="button" onClick={addText}>＋ 텍스트</button><button type="button" onClick={addPhotoSlot}>＋ 사진</button><button type="button" onClick={addShape}>＋ 도형</button></div>
          <label>확대 <input type="range" min="0.35" max="0.95" step="0.05" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /> <span>{Math.round(zoom * 100)}%</span></label>
        </div>
        <ComponentCanvas poster={poster} selectedId={selectedId} zoom={zoom} select={select} update={(id, patch) => { update(id, patch); setSaved(false) }} stageRef={stageRef} />
      </section>
      <aside className="poster-inspector panel">
        <div className="panel-title"><span>1</span><h2>전단지 내용</h2></div>
        <p className="poster-help">입력한 문구는 미리보기에 바로 반영됩니다. 캔버스 안에서는 위치와 크기를 조절할 수 있어요.</p>
        <input ref={fileRef} className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { uploadFile(event.target.files?.[0]); event.target.value = '' }} />
        <div className="poster-fields">{textComponents.map((item) => <label className="poster-field" key={item.id}><span>{item.label || POSTER_FIELDS.find(([key]) => key === item.fieldKey)?.[1] || '텍스트'}</span><textarea rows={item.content?.length > 45 ? 3 : 2} value={item.content || ''} onChange={(event) => { update(item.id, { content: event.target.value }); setSaved(false) }} placeholder={POSTER_FIELDS.find(([key]) => key === item.fieldKey)?.[2] || '문구를 입력해 주세요'} />{textOverflows(item) && <small className="poster-overflow-warning">텍스트가 영역을 넘을 수 있어요. 캔버스에서 크기나 글자 크기를 조절해 주세요.</small>}</label>)}</div>
        {selected && <div className="poster-properties">
          <div className="panel-title"><span>2</span><h2>선택한 요소</h2></div>
          <div className="poster-selected-head"><strong>{selected.label || (selected.type === 'shape' ? '도형' : selected.type === 'image' ? '사진' : '텍스트')}</strong><button type="button" className="text-action danger-text" onClick={() => { removeComponent(selected.id); setSaved(false) }}>삭제</button></div>
          {selected.type === 'text' && <>
            <label className="poster-property">글자 크기<input type="number" min="8" max="120" value={selected.fontSize || 24} onChange={(e) => { update(selected.id, { fontSize: Number(e.target.value) }); setSaved(false) }} /></label>
            <label className="poster-property">글자 색상<input type="color" value={selected.color || '#34302b'} onChange={(e) => { update(selected.id, { color: e.target.value }); setSaved(false) }} /></label>
            <label className="poster-property">배경색<input type="color" value={selected.fill || '#fffdf8'} onChange={(e) => { update(selected.id, { fill: e.target.value }); setSaved(false) }} /></label>
            <label className="poster-property">정렬<select value={selected.align || 'left'} onChange={(e) => { update(selected.id, { align: e.target.value }); setSaved(false) }}><option value="left">왼쪽</option><option value="center">가운데</option><option value="right">오른쪽</option></select></label>
            <label className="poster-check"><input type="checkbox" checked={selected.fontStyle === 'bold'} onChange={(e) => { update(selected.id, { fontStyle: e.target.checked ? 'bold' : 'normal' }); setSaved(false) }} /> 굵게</label>
          </>}
          {selected.type === 'image' && <>
            <button type="button" className="secondary-button poster-replace" onClick={() => fileRef.current?.click()}>{selected.assetId ? '사진 교체' : '사진 업로드'}</button>
            <label className="poster-property">자르기 확대<input type="range" min="1" max="3" step="0.05" value={selected.cropZoom || 1} onChange={(e) => { update(selected.id, { cropZoom: Number(e.target.value) }); setSaved(false) }} /></label>
            <label className="poster-property">자르기 가로 위치<input type="range" min="0" max="1" step="0.01" value={selected.cropX ?? 0.5} onChange={(e) => { update(selected.id, { cropX: Number(e.target.value) }); setSaved(false) }} /></label>
            <label className="poster-property">자르기 세로 위치<input type="range" min="0" max="1" step="0.01" value={selected.cropY ?? 0.5} onChange={(e) => { update(selected.id, { cropY: Number(e.target.value) }); setSaved(false) }} /></label>
            <label className="poster-property">회전<input type="number" min="-180" max="180" value={selected.rotation || 0} onChange={(e) => { update(selected.id, { rotation: Number(e.target.value) }); setSaved(false) }} /></label>
            <label className="poster-property">투명도<input type="range" min="0.1" max="1" step="0.05" value={selected.opacity ?? 1} onChange={(e) => { update(selected.id, { opacity: Number(e.target.value) }); setSaved(false) }} /></label>
          </>}
          {selected.type === 'shape' && <>
            <label className="poster-property">배경색<input type="color" value={selected.fill || '#e8d8b5'} onChange={(e) => { update(selected.id, { fill: e.target.value }); setSaved(false) }} /></label>
            <label className="poster-property">테두리색<input type="color" value={selected.stroke || '#9c8250'} onChange={(e) => { update(selected.id, { stroke: e.target.value }); setSaved(false) }} /></label>
            <label className="poster-property">투명도<input type="range" min="0.1" max="1" step="0.05" value={selected.opacity ?? 1} onChange={(e) => { update(selected.id, { opacity: Number(e.target.value) }); setSaved(false) }} /></label>
          </>}
          <div className="poster-layer-actions"><button type="button" onClick={() => reorder(selected.id, -1)}>뒤로</button><button type="button" onClick={() => reorder(selected.id, 1)}>앞으로</button></div>
        </div>}
        {notice && <p className={`poster-notice${notice.includes('못') || notice.includes('실패') ? ' error' : ''}`} role="status">{notice}</p>}
      </aside>
    </div>
  </main>
}
