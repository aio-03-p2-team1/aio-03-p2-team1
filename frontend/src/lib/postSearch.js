// 실종 정보 게시판 글(회원 글·공공데이터 분실 신고)로 '우리 아이 찾기' 검색 화면을 미리 채운다.
// 검색 화면은 채운 뒤 바로 찾는다(사진이 있으면 서버 사진 분석을 마친 뒤). 사용자는 결과를 보고 입력을 고쳐 다시 찾을 수 있다.
// 로그인 화면을 거쳐도 남도록 sessionStorage 에 잠깐 넣었다가 검색 화면이 한 번 읽고 지운다.
// 개인정보(신고자·연락처·칩 번호)는 서버가 이미 빼고 보내며, 여기서도 쓰지 않는다.
import { sexLabel } from './post.js'

const KEY = 'dasimanna:post-search'
const SPECIES = ['dog', 'cat', 'etc']

function clean(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim()
}

// 게시글 → 검색 화면 값. today 는 'YYYY-MM-DD'(미래 날짜·잘못된 날짜면 오늘로).
// photoUrl: 게시글 사진 주소(회원 글은 우리 서버, 분실 신고는 공공데이터 주소). 사진이 없으면 비움.
export function postToSearch(post, today, photoUrl = '') {
  const lostDate = /^\d{4}-\d{2}-\d{2}$/.test(post?.lost_date || '') && post.lost_date <= today ? post.lost_date : today
  // 검색 지역은 시·도 이름이다. 분실 신고의 지역은 '경기도 수원시'처럼 시·군·구까지 있어 첫 낱말만 쓴다.
  const sido = clean(post?.region).split(' ')[0] || ''
  const address = clean(post?.lost_place) || clean(post?.region)
  // 품종은 서버가 검증한 코드로 선택란에 전달한다. 나머지 특징만 설명에 붙인다.
  const facts = [
    post?.color && `털색: ${clean(post.color)}`,
    sexLabel(post?.sex) && `성별: ${sexLabel(post.sex)}`,
    post?.age && `나이: ${clean(post.age)}`,
  ].filter(Boolean)
  const lines = [
    facts.join(', '),
    clean(post?.description),
    post?.happen_place && `마지막으로 본 장소: ${clean(post.happen_place)}`,
  ].filter(Boolean)
  return {
    form: {
      breed_code: SPECIES.includes(post?.species) ? clean(post?.breed_code) : '',
      species: SPECIES.includes(post?.species) ? post.species : '',
      lost_date: lostDate,
      description: lines.join('\n').slice(0, 1000),
    },
    location: sido ? { region: sido, address } : null,
    source: { id: post?.id || '', title: clean(post?.pet_name) || clean(post?.breed) || '실종 정보' },
    photo: post?.has_photo && photoUrl ? photoUrl : '',
  }
}

export function savePostSearch(value, storage = globalThis.sessionStorage) {
  try {
    storage?.setItem(KEY, JSON.stringify(value))
  } catch {
    // 저장소를 못 쓰면(사생활 보호 모드 등) 미리 채우기만 빠진다.
  }
}

// 한 번 읽고 지운다(새로고침해도 다시 채우지 않게).
export function takePostSearch(storage = globalThis.sessionStorage) {
  try {
    const raw = storage?.getItem(KEY)
    storage?.removeItem(KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
