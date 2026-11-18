// 머리말의 로고·메뉴를 눌렀을 때, 이미 그 페이지에 있으면 화면을 새로 불러온다.
// 다른 페이지로 갈 때는 평소처럼 앱 안에서 이동해 검색 결과 등 화면 상태를 유지한다.
export function shouldReloadOnNav(currentPath, to, event = {}) {
  if (event.defaultPrevented) return false
  if (event.button !== undefined && event.button !== 0) return false
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false
  return normalize(currentPath) === normalize(to)
}

function normalize(path) {
  const trimmed = String(path || '/').replace(/\/+$/, '')
  return trimmed || '/'
}
