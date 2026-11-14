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
