import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Stage, Layer, Rect, Text, Image as KonvaImage, Transformer } from 'react-konva'
import { API_BASE, api } from '../lib/api.js'
import { usePosterStore } from '../lib/posterStore.js'

const FIELDS = [
  ['title', '전단지 제목', '강아지를 찾습니다'],
  ['pet_name', '동물 이름', '이름을 입력해 주세요'],
  ['species_breed', '동물 종류 및 품종', '예: 강아지 · 말티즈'],
  ['lost_datetime', '실종 날짜 및 시간', '예: 2026년 11월 17일 오후 3시'],
  ['lost_place', '실종 장소', '실종 장소를 입력해 주세요'],
  ['features', '신체적 특징', '털색, 크기, 목줄 등 특징'],
  ['contact', '발견 시 연락처', '연락처를 입력해 주세요'],
  ['extra_description', '추가 설명', '사례금 등 추가 내용을 적어 주세요']
]
const fieldMap = Object.fromEntries(FIELDS.map(([key, label]) => [key, label]))
const makeId = () => crypto.randomUUID().replaceAll('-', '')

function templateDocument(template) {
  const components = structuredClone(template.components).map((item) => ({ ...item, id: item.id || makeId() }))
  const layouts = {
    basic: { title: [42, 74], pet_name: [625, 58], species_breed: [690, 38], lost_datetime: [735, 38], lost_place: [780, 42], features: [828, 42], extra_description: [876, 42], contact: [970, 76] },
    info: { title: [42, 70], pet_name: [590, 50], species_breed: [645, 38], lost_datetime: [688, 38], lost_place: [731, 38], features: [774, 90], extra_description: [870, 42], contact: [962, 70] },
    urgent: { title: [38, 88], pet_name: [665, 56], species_breed: [722, 38], lost_datetime: [765, 38], lost_place: [808, 38], features: [851, 38], extra_description: [894, 38], contact: [968, 90] }
  }
  const layout = layouts[template.id] || layouts.basic
  components.forEach((item) => {
    if (item.type === 'text' && layout[item.fieldKey]) {
      const [y, height] = layout[item.fieldKey]
      item.y = y; item.height = height; item.x = 58; item.width = 678
      item.label = fieldMap[item.fieldKey] || item.label
    }
  })
  const existing = new Set(components.map((item) => item.fieldKey).filter(Boolean))
  const defaults = FIELDS.filter(([key]) => !existing.has(key)).map(([key, label, placeholder], index) => ({
    id: makeId(), type: 'text', label, fieldKey: key, content: placeholder,
    x: 58, y: layout[key]?.[0] ?? 670 + index * 43, width: 678, height: layout[key]?.[1] ?? 36, fontSize: 17,
    color: '#51493f', zIndex: components.length + index + 1
  }))
  return { templateId: template.id, width: template.width, height: template.height, components: [...components, ...defaults] }
}

function useAssetImage(assetId) {
  const [image, setImage] = useState(null)
  useEffect(() => {
    if (!assetId) { setImage(null); return }
    let live = true
    const next = new window.Image()
    next.onload = () => live && setImage(next)
    next.onerror = () => live && setImage(null)
    next.src = `${API_BASE}/poster/assets/${assetId}`
    return () => { live = false }
  }, [assetId])
  return image
}

function imageCrop(image, item) {
  if (!image) return undefined
  const boxRatio = item.width / item.height
  const sourceRatio = image.width / image.height
  let width = image.width
  let height = image.height
  if (sourceRatio > boxRatio) width = image.height * boxRatio
  else height = image.width / boxRatio
  const zoom = Math.max(1, Math.min(3, Number(item.cropZoom) || 1))
  width /= zoom; height /= zoom
  const x = (image.width - width) * Math.max(0, Math.min(1, Number(item.cropX ?? 0.5)))
  const y = (image.height - height) * Math.max(0, Math.min(1, Number(item.cropY ?? 0.5)))
  return { x, y, width, height }
}

function CanvasItem({ item, selected, onSelect, onChange, registerNode }) {
  const image = useAssetImage(item.assetId)
  const common = {
    id: item.id, x: item.x, y: item.y, width: item.width, height: item.height,
    rotation: item.rotation || 0, draggable: true, opacity: item.opacity ?? 1,
    onClick: onSelect, onTap: onSelect,
    onDragEnd: (event) => onChange({ x: event.target.x(), y: event.target.y() }),
    onTransformEnd: (event) => {
      const node = event.target
      const scaleX = node.scaleX(); const scaleY = node.scaleY()
      node.scaleX(1); node.scaleY(1)
      onChange({ x: node.x(), y: node.y(), width: Math.max(20, node.width() * scaleX), height: Math.max(20, node.height() * scaleY), rotation: node.rotation() })
    },
    ref: registerNode
  }
  if (item.type === 'image') {
    return <>
      <Rect {...common} fill="#eee9df" stroke={selected ? '#4c7757' : '#d8d0c4'} strokeWidth={selected ? 2 : 1} />
      {image && <KonvaImage {...common} image={image} crop={imageCrop(image, item)} />}
      {!image && <Text {...common} text="사진을 추가해 주세요" align="center" verticalAlign="middle" fill="#8b8275" fontSize={18} listening={false} />}
    </>
  }
  if (item.type === 'shape') {
    return <Rect {...common} fill={item.fill || '#e8d8b5'} stroke={item.stroke || '#9c8250'} strokeWidth={item.strokeWidth ?? 2} />
  }
  return <>
    {item.fill && <Rect {...common} fill={item.fill} stroke={selected ? '#4c7757' : undefined} strokeWidth={selected ? 2 : 0} />}
    <Text {...common} text={item.content || ''} fontSize={item.fontSize || 24} fill={item.color || '#34302b'} fontStyle={item.fontStyle || 'normal'} align={item.align || 'left'} verticalAlign="middle" wrap="word" padding={item.padding ?? 4} />
  </>
}

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
    <Stage ref={stageRef} width={poster.width * zoom} height={poster.height * zoom} scaleX={zoom} scaleY={zoom}
      onMouseDown={(event) => { if (event.target === event.target.getStage()) select(null) }}
      onTouchStart={(event) => { if (event.target === event.target.getStage()) select(null) }}>
      <Layer>
        <Rect x={0} y={0} width={poster.width} height={poster.height} fill="#fffdf8" shadowColor="#342e23" shadowBlur={12} shadowOpacity={0.12} onMouseDown={() => select(null)} onTouchStart={() => select(null)} />
        {sorted.map((item) => <CanvasItem key={item.id} item={item} selected={selectedId === item.id} onSelect={() => select(item.id)} onChange={(patch) => update(item.id, patch)} registerNode={(node) => { if (node) nodes.current[item.id] = node; else delete nodes.current[item.id] }} />)}
        <Transformer ref={transformRef} rotateEnabled anchorSize={9} borderStroke="#4c7757" anchorStroke="#4c7757" anchorFill="#fff" />
      </Layer>
    </Stage>
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
        else return api(`/poster/templates/${list.items[0]?.id || 'basic'}`).then((template) => live && setPoster(templateDocument(template)))
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
      const previousFields = Object.fromEntries(poster.components.filter((item) => item.fieldKey).map((item) => [item.fieldKey, item.content]))
      const next = templateDocument(template)
      next.components = next.components.map((item) => item.fieldKey && previousFields[item.fieldKey] !== undefined ? { ...item, content: previousFields[item.fieldKey] } : item)
      const oldPhotos = poster.components.filter((item) => item.type === 'image' && item.assetId)
      const nextPhotos = next.components.filter((item) => item.type === 'image')
      oldPhotos.forEach((photo, index) => { if (nextPhotos[index]) Object.assign(nextPhotos[index], { assetId: photo.assetId, opacity: photo.opacity }) })
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
        ? await api(`/posters/${posterId}`, { method: 'PUT', body: poster })
        : await api('/posters', { method: 'POST', body: poster })
      setSaved(true); setNotice('전단지를 저장했어요.')
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
    link.href = stageInstance.toDataURL({ pixelRatio: 2 / zoom, mimeType: 'image/png' })
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
    const imageUrl = stageInstance.toDataURL({ pixelRatio: 2 / zoom, mimeType: 'image/png' })
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
        <div className="poster-fields">{textComponents.map((item) => <label className="poster-field" key={item.id}><span>{item.label || fieldMap[item.fieldKey] || '텍스트'}</span><textarea rows={item.content?.length > 45 ? 3 : 2} value={item.content || ''} onChange={(event) => { update(item.id, { content: event.target.value }); setSaved(false) }} placeholder={FIELDS.find(([key]) => key === item.fieldKey)?.[2] || '문구를 입력해 주세요'} />{item.id === selectedId && item.height < 45 && item.content?.length > 30 && <small className="poster-overflow-warning">텍스트가 영역 높이를 넘을 수 있어요. 캔버스에서 크기를 조절해 주세요.</small>}</label>)}</div>
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
