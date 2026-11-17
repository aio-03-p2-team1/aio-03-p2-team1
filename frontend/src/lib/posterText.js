export const POSTER_FONT = '"Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif'
export const POSTER_LINE_HEIGHT = 1.3

export function textOverflows(component, measureText) {
  const text = component?.content
  if (!text) return false
  const fontSize = Number(component.fontSize) || 24
  const padding = Number(component.padding ?? 4)
  const maxWidth = Math.max(1, Number(component.width) - padding * 2)
  let measure = measureText
  if (!measure && typeof document !== 'undefined') {
    const context = document.createElement('canvas').getContext('2d')
    if (context) {
      context.font = `${component.fontStyle === 'bold' ? 'bold ' : ''}${fontSize}px ${POSTER_FONT}`
      measure = (value) => context.measureText(value).width
    }
  }
  if (!measure) measure = (value) => Array.from(value).length * fontSize * 0.58

  let lines = 0
  for (const paragraph of String(text).split('\n')) {
    let line = ''
    for (const character of Array.from(paragraph)) {
      const candidate = line + character
      if (line && measure(candidate) > maxWidth) {
        lines += 1
        line = character.trim() ? character : ''
      } else {
        line = candidate
      }
      if (measure(line || character) > maxWidth) return true
    }
    lines += 1
  }
  const lineHeight = fontSize * (Number(component.lineHeight) || POSTER_LINE_HEIGHT)
  return lines * lineHeight + padding * 2 > Number(component.height)
}
