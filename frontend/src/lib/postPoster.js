// 실종 정보 게시판 글(회원 글·공공데이터 분실 신고)로 전단지 문구를 채운다.
// 연락처는 게시글에 없으므로(개인정보는 서버가 빼고 보냄) 템플릿 안내 문구를 그대로 두어 사용자가 직접 넣게 한다.
// 상세 화면이 채울 문구·사진 자산을 sessionStorage 에 두면 전단지 편집기(/poster)가 새 전단지에 한 번 적용하고 지운다.
// 저장은 사용자가 편집기에서 직접 한다.
import { postSpeciesLabel, postTitle, sexLabel } from './post.js'

const clean = (value) => String(value ?? '').replace(/\s+/g, ' ').trim()

function cut(text, max) {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

/** 'YYYY-MM-DD' → '2026년 11월 14일'. 형식이 다르면 빈 문자열. */
export function koreanDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '')
  return m ? `${Number(m[1])}년 ${Number(m[2])}월 ${Number(m[3])}일` : ''
}

/** 게시글 → 전단지 fieldKey 별 문구. 값이 없으면 그 키를 넣지 않는다(템플릿 문구 유지). */
export function postToPosterFields(post) {
  const species = post?.species ? postSpeciesLabel(post.species) : ''
  const facts = [
    clean(post?.color) && `털색 ${clean(post.color)}`,
    sexLabel(post?.sex),
    clean(post?.age) && `나이 ${clean(post.age)}`,
  ].filter(Boolean)
  const description = clean(post?.description)
  const fields = {
    title: postTitle(post),
    pet_name: clean(post?.pet_name) || (post?.source === 'lost_api' ? '이름 미상' : ''),
    species_breed: [species !== '미확인' && species, clean(post?.breed)].filter(Boolean).join(' · '),
    lost_datetime: koreanDate(post?.lost_date),
    lost_place: clean(post?.lost_place) || clean(post?.happen_place) || clean(post?.region),
    features: cut([facts.join(', '), description].filter(Boolean).join(' / '), 120),
    extra_description: post?.source === 'lost_api' ? '공공데이터 분실 신고를 바탕으로 만든 전단지예요.' : '',
  }
  return Object.fromEntries(Object.entries(fields).filter(([, v]) => v))
}

/** 전단지 문서의 fieldKey 텍스트를 바꾼 새 문서를 돌려준다. */
export function fillPoster(poster, fields) {
  return {
    ...poster,
    components: poster.components.map((item) =>
      item.type === 'text' && item.fieldKey && fields[item.fieldKey] !== undefined ? { ...item, content: fields[item.fieldKey] } : item
    ),
  }
}

/** 첫 번째 사진 칸에 업로드한 자산 ID 를 넣는다. 사진 칸이 없으면 그대로 둔다. */
export function setPosterPhoto(poster, assetId) {
  let done = false
  return {
    ...poster,
    components: poster.components.map((item) => {
      if (done || item.type !== 'image') return item
      done = true
      return { ...item, assetId }
    }),
  }
}

const DRAFT_KEY = 'dasimanna:post-poster'

/** 편집기에 넘길 문구(fields)와 사진 자산 ID(assetId)를 잠깐 둔다. */
export function savePosterDraft(draft, storage = globalThis.sessionStorage) {
  try {
    storage?.setItem(DRAFT_KEY, JSON.stringify(draft))
  } catch {
    // 저장소를 못 쓰면 빈 전단지로 열린다.
  }
}

/** 넘겨받은 초안을 읽기만 한다(개발 모드에서 효과가 두 번 돌아도 둘 다 읽도록). 적용한 뒤 clearPosterDraft 로 지운다. */
export function peekPosterDraft(storage = globalThis.sessionStorage) {
  try {
    const raw = storage?.getItem(DRAFT_KEY)
    const draft = raw ? JSON.parse(raw) : null
    return draft && typeof draft.fields === 'object' && draft.fields ? draft : null
  } catch {
    return null
  }
}

export function clearPosterDraft(storage = globalThis.sessionStorage) {
  try {
    storage?.removeItem(DRAFT_KEY)
  } catch {
    // 무시
  }
}

/** 템플릿으로 만든 새 전단지에 초안을 적용한다. */
export function applyPosterDraft(poster, draft) {
  const filled = fillPoster(poster, draft.fields)
  return draft.assetId && /^[0-9a-f]{32}$/.test(draft.assetId) ? setPosterPhoto(filled, draft.assetId) : filled
}
