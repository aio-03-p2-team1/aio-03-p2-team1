const PHOTO_FORMAT_ERROR = 'JPG, PNG, WEBP 형식의 사진만 사용할 수 있어요.'
const PHOTO_TOO_LARGE_ERROR = '사진은 8MB 이하로 선택해 주세요.'
const PHOTO_UNSUITABLE_MESSAGE = '다른 사진을 사용해 주세요.'
const SUPPORTED_PHOTO_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

export function photoSelectionError(file) {
  if (!SUPPORTED_PHOTO_TYPES.has(file?.type)) return PHOTO_FORMAT_ERROR
  if (file.size > 8 * 1024 * 1024) return PHOTO_TOO_LARGE_ERROR
  return ''
}

export function photoAnalysisError(error) {
  if (['invalid_photo', 'unsupported_photo_format'].includes(error?.code)) return PHOTO_FORMAT_ERROR
  return '오류가 발생했습니다.'
}

export function unsuitablePhotoMessage(result) {
  if (result?.suitable) return ''
  return typeof result?.message === 'string' && result.message.trim()
    ? result.message.trim()
    : PHOTO_UNSUITABLE_MESSAGE
}
