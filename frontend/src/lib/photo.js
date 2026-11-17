const PHOTO_UNSUITABLE_MESSAGE = '다른 사진을 사용해 주세요.'
const SUPPORTED_PHOTO_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const PHOTO_ERROR_MESSAGES = {
  unsupported_photo_format: 'JPG, PNG, WEBP 형식의 사진만 사용할 수 있어요.',
  photo_too_large: '사진은 8MB 이하로 선택해 주세요.',
  photo_analysis_failed: '오류가 발생했습니다.',
}
const PHOTO_REASON_MESSAGES = {
  animal_not_detected: '사진에서 동물을 확인하지 못했어요. 동물이 보이는 사진을 올려 주세요.',
  appearance_unclear: '동물의 외형을 알아보기 어려워요. 더 선명한 사진을 올려 주세요.',
  subject_not_distinct: '찾을 동물이 중심에서 구분되지 않아요. 동물이 중심에 보이는 사진을 올려 주세요.',
}

export function photoSelectionError(file) {
  if (!SUPPORTED_PHOTO_TYPES.has(file?.type)) return 'unsupported_photo_format'
  if (file.size > 8 * 1024 * 1024) return 'photo_too_large'
  return null
}

export function photoAnalysisError(error) {
  if (['invalid_photo', 'unsupported_photo_format'].includes(error?.code)) return 'unsupported_photo_format'
  return 'photo_analysis_failed'
}

export function photoErrorMessage(code) {
  return PHOTO_ERROR_MESSAGES[code] || PHOTO_ERROR_MESSAGES.photo_analysis_failed
}

export function unsuitablePhotoMessage(result) {
  if (result?.suitable) return ''
  return PHOTO_REASON_MESSAGES[result?.reason_code] || PHOTO_UNSUITABLE_MESSAGE
}

// 사진 분석 특징 중 설명 글에 이미 있는 것은 뺀다(같은 내용이 두 번 적히던 문제).
// 털색은 같은 색의 다른 표현(하얀·백색 등)도 이미 있는 것으로 본다. 띄어쓰기는 무시한다(빨간 목줄 = 빨간목줄).
const COLOR_WORDS = {
  흰색: ['흰', '하얀', '하양', '백색', '화이트'],
  검정: ['검정', '검은', '까만', '블랙'],
  갈색: ['갈색', '브라운'],
  크림: ['크림', '베이지'],
  회색: ['회색', '그레이', '잿빛'],
  노랑: ['노랑', '노란', '황색'],
  황갈색: ['황갈', '누런'],
}

export function newPhotoTraits(traits, text) {
  const plain = String(text || '').replace(/\s+/g, '')
  return traits.filter((trait) => {
    const words = COLOR_WORDS[trait] || [trait]
    return !words.some((word) => plain.includes(String(word).replace(/\s+/g, '')))
  })
}

// 설명 글 앞에 붙일 한 줄. 새 특징이 없어도 '사진을 확인했다'는 표시는 남긴다
// (검색 에이전트가 이 줄로 사진을 받았는지 판단해 사진을 다시 요청하지 않는다).
export function photoTraitLine(traits, text) {
  if (!traits.length) return ''
  const fresh = newPhotoTraits(traits, text)
  return `사진에서 확인한 특징: ${fresh.length ? fresh.join(', ') : '글 내용과 같음'}`
}
