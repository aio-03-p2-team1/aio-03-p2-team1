import { useEffect, useState } from 'react'
import { Rect, Text, Image as KonvaImage } from 'react-konva'
import { API_BASE } from '../lib/api.js'
import { POSTER_FONT, POSTER_LINE_HEIGHT } from '../lib/posterText.js'

// 전단지 편집기(PosterPage)와 전단지 상세(PosterDetailPage)가 함께 쓰는 캔버스 요소.
// readOnly 이면 끌기·선택·변형을 끄고 그대로 그리기만 한다.

export function useAssetImage(assetId) {
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

export function imageCrop(image, item) {
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

export function CanvasItem({ item, selected, onSelect, onChange, registerNode, readOnly = false }) {
  const image = useAssetImage(item.assetId)
  const common = {
    id: item.id, x: item.x, y: item.y, width: item.width, height: item.height,
    rotation: item.rotation || 0, draggable: !readOnly, listening: !readOnly, opacity: item.opacity ?? 1,
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
      {!image && !readOnly && <Text {...common} fontFamily={POSTER_FONT} lineHeight={item.lineHeight || POSTER_LINE_HEIGHT} text="사진을 추가해 주세요" align="center" verticalAlign="middle" fill="#8b8275" fontSize={18} listening={false} />}
    </>
  }
  if (item.type === 'shape') {
    return <Rect {...common} fill={item.fill || '#e8d8b5'} stroke={item.stroke || '#9c8250'} strokeWidth={item.strokeWidth ?? 2} />
  }
  return <>
    {item.fill && <Rect {...common} fill={item.fill} stroke={selected ? '#4c7757' : undefined} strokeWidth={selected ? 2 : 0} />}
    <Text {...common} fontFamily={POSTER_FONT} lineHeight={item.lineHeight || POSTER_LINE_HEIGHT} text={item.content || ''} fontSize={item.fontSize || 24} fill={item.color || '#34302b'} fontStyle={item.fontStyle || 'normal'} align={item.align || 'left'} verticalAlign="middle" wrap="word" padding={item.padding ?? 4} />
  </>
}
