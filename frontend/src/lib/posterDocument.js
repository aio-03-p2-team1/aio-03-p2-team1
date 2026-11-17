export const POSTER_FIELDS = [
  ['title', '전단지 제목', '강아지를 찾습니다'],
  ['pet_name', '동물 이름', '이름을 입력해 주세요'],
  ['species_breed', '동물 종류 및 품종', '예: 강아지 · 말티즈'],
  ['lost_datetime', '실종 날짜 및 시간', '예: 2026년 11월 17일 오후 3시'],
  ['lost_place', '실종 장소', '실종 장소를 입력해 주세요'],
  ['features', '신체적 특징', '털색, 크기, 목줄 등 특징'],
  ['contact', '발견 시 연락처', '연락처를 입력해 주세요'],
  ['extra_description', '추가 설명', '사례금 등 추가 내용을 적어 주세요']
]

const fieldMap = Object.fromEntries(POSTER_FIELDS.map(([key, label]) => [key, label]))
const layouts = {
  basic: { title: [42, 74], pet_name: [625, 58], species_breed: [690, 38], lost_datetime: [735, 38], lost_place: [780, 42], features: [828, 42], extra_description: [876, 42], contact: [970, 76] },
  info: { title: [42, 70], pet_name: [590, 50], species_breed: [645, 38], lost_datetime: [688, 38], lost_place: [731, 38], features: [774, 90], extra_description: [870, 42], contact: [962, 70] },
  urgent: { title: [38, 88], pet_name: [665, 56], species_breed: [722, 38], lost_datetime: [765, 38], lost_place: [808, 38], features: [851, 38], extra_description: [894, 38], contact: [968, 90] }
}
const defaultId = () => globalThis.crypto.randomUUID().replaceAll('-', '')

export function createPosterFromTemplate(template, makeId = defaultId) {
  const components = structuredClone(template.components).map((item) => ({ ...item, id: item.id || makeId() }))
  const layout = layouts[template.id] || layouts.basic
  components.forEach((item) => {
    if (item.type === 'text' && layout[item.fieldKey]) {
      const [y, height] = layout[item.fieldKey]
      item.y = y; item.height = height; item.x = 58; item.width = 678
      item.label = fieldMap[item.fieldKey] || item.label
    }
  })
  const existing = new Set(components.map((item) => item.fieldKey).filter(Boolean))
  const defaults = POSTER_FIELDS.filter(([key]) => !existing.has(key)).map(([key, label, placeholder], index) => ({
    id: makeId(), type: 'text', label, fieldKey: key, content: placeholder,
    x: 58, y: layout[key]?.[0] ?? 670 + index * 43, width: 678, height: layout[key]?.[1] ?? 36, fontSize: 17,
    color: '#51493f', zIndex: components.length + index + 1
  }))
  return { templateId: template.id, width: template.width, height: template.height, components: [...components, ...defaults] }
}

export function switchPosterTemplate(previous, template, makeId = defaultId) {
  const next = createPosterFromTemplate(template, makeId)
  const fields = Object.fromEntries(previous.components.filter((item) => item.fieldKey).map((item) => [item.fieldKey, item.content]))
  next.components = next.components.map((item) => item.fieldKey && fields[item.fieldKey] !== undefined ? { ...item, content: fields[item.fieldKey] } : item)

  const photos = previous.components.filter((item) => item.type === 'image' && item.assetId)
  const imageSlots = next.components.filter((item) => item.type === 'image')
  if (photos.length && imageSlots.length) {
    const frame = imageSlots[0]
    const cols = Math.ceil(Math.sqrt(photos.length))
    const rows = Math.ceil(photos.length / cols)
    const gap = 12
    const tileWidth = (frame.width - gap * (cols - 1)) / cols
    const tileHeight = (frame.height - gap * (rows - 1)) / rows
    photos.forEach((photo, index) => {
      const column = index % cols
      const row = Math.floor(index / cols)
      const target = imageSlots[index] || { ...frame, id: makeId(), zIndex: Math.max(0, ...next.components.map((item) => item.zIndex || 0)) + index + 1 }
      Object.assign(target, {
        assetId: photo.assetId,
        x: frame.x + column * (tileWidth + gap),
        y: frame.y + row * (tileHeight + gap),
        width: tileWidth,
        height: tileHeight,
        opacity: photo.opacity ?? 1,
        rotation: photo.rotation || 0,
        cropX: photo.cropX ?? 0.5,
        cropY: photo.cropY ?? 0.5,
        cropZoom: photo.cropZoom || 1
      })
      if (!imageSlots[index]) next.components.push(target)
    })
  }
  return next
}
