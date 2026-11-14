import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, API_BASE } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDate } from '../lib/format.js'
import {
  BOARD_PERIODS, DEFAULT_BOARD_DAYS, boardSummary, localDate, MAX_PHOTO_BYTES, dataUrlBytes, POST_SPECIES,
  postPath, postPhotoPath, postTitle, validatePost
} from '../lib/post.js'
import Pagination from '../components/Pagination.jsx'
import RegionPicker from '../components/RegionPicker.jsx'
import { useToast } from '../components/Toast.jsx'
import { useRegions } from './useRegions.js'

const EMPTY = { pet_name: '', species: '', region: '', lost_place: '', lost_date: '', breed: '', description: '' }

export default function PostBoardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const regions = useRegions()
  const [species, setSpecies] = useState('all')
  const [region, setRegion] = useState('')
  const [days, setDays] = useState(DEFAULT_BOARD_DAYS) // 분실 날짜 기준 최근 며칠
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [reload, setReload] = useState(0)
  const [formOpen, setFormOpen] = useState(false)

  useEffect(() => {
    document.title = '다시 만나 · 실종 정보 게시판'
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    // 필터·페이지는 서버가 캐시된 목록에서 처리한다(외부 API 를 다시 부르지 않음).
    const query = new URLSearchParams({ species, days: String(days), page: String(page) })
    if (region) query.set('region', region)
    setStatus('loading')
    api(`/posts?${query}`, { auth: false, signal: controller.signal })
      .then((body) => {
        setData(body)
        setStatus('ready')
        setError(null)
      })
      .catch((err) => {
        if (err.name === 'AbortError') return
        setError(err)
        setStatus('error')
      })
    return () => controller.abort()
  }, [species, region, days, page, reload, user])

  // 필터를 바꾸면 첫 페이지부터 다시 본다.
  function changeFilter(setter) {
    return (e) => {
      setter(e.target.value)
      setPage(1)
    }
  }

  function openForm() {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent('/board?write=1')}`)
      return
    }
    setFormOpen(true)
  }

  useEffect(() => {
    if (user && new URLSearchParams(window.location.search).get('write') === '1') setFormOpen(true)
  }, [user])

  return (
    <main className="page-main">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>실종 정보 게시판</span>
      </div>
      <div className="page-heading board-heading">
        <div>
          <span className="eyebrow">함께 찾는 공간</span>
          <h1>실종 정보 게시판</h1>
          <p>잃어버린 반려동물의 정보를 등록하고, 회원 글과 공공데이터 분실 신고를 함께 살펴보세요.</p>
        </div>
        <button type="button" className="primary-button" onClick={openForm} aria-expanded={formOpen}>
          실종 정보 등록 ↗
        </button>
      </div>

      {formOpen && user && (
        <PostForm
          regions={regions}
          onCancel={() => setFormOpen(false)}
          onCreated={(post) => {
            setFormOpen(false)
            setReload((n) => n + 1)
            navigate(`/board/${post.id}`)
          }}
        />
      )}

      <section className="board-list-section" aria-labelledby="posts-title">
        <div className="section-head">
          <div>
            <h2 id="posts-title">등록된 실종 정보</h2>
            <p>
              게시글을 선택하면 상세 페이지로 이동합니다.
              {data && ` ${boardSummary(data)}`}
            </p>
          </div>
          <div className="filters">
            <label>
              동물 종류
              <select value={species} onChange={changeFilter(setSpecies)}>
                <option value="all">전체</option>
                {POST_SPECIES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label>
              지역
              <select value={region} onChange={changeFilter(setRegion)} disabled={!regions.list.length}>
                <option value="">전체 지역</option>
                {regions.list.map((r) => <option key={r.code} value={r.name}>{r.name}</option>)}
              </select>
            </label>
            <label>
              기간
              <select value={days} onChange={changeFilter((v) => setDays(Number(v)))}>
                {BOARD_PERIODS.map((d) => <option key={d} value={d}>최근 {d}일</option>)}
              </select>
            </label>
          </div>
        </div>
        {/* 분실 신고를 못 불러왔으면 회원 글만 보이는 이유를 알린다(빈 결과와 구분) */}
        {status === 'ready' && ['unavailable', 'loading'].includes(data.lost?.status) && (
          <p className="fineprint" role="status">{data.lost.message}</p>
        )}

        {status === 'loading' && <p className="state-box">게시글을 불러오고 있어요…</p>}
        {status === 'error' && (
          <div className="state-box state-error" role="alert">
            <strong>게시글을 불러오지 못했어요.</strong>
            <p>{errorMessage(error)}</p>
            <button type="button" className="secondary-button" onClick={() => setReload((n) => n + 1)}>다시 시도</button>
          </div>
        )}
        {status === 'ready' && data.items.length === 0 && (
          <p className="empty-results">
            {species === 'all' && !region ? '이 기간에 등록된 실종 정보가 없어요. 기간을 넓히거나 첫 게시글을 등록해 보세요.' : '선택한 조건의 게시글이 없어요.'}
          </p>
        )}
        {status === 'ready' && data.items.length > 0 && (
          <div className="board-list" aria-live="polite">
            {data.items.map((post) => (
              <Link key={post.id} className="post-card" to={postPath(post)}>
                <PostPhoto post={post} />
                <span className="post-card-body">
                  {post.mine && <span className="sample-label">내 글</span>}
                  <strong>{postTitle(post)}</strong>
                  <p>{post.lost_place || post.region} · {formatDate(post.lost_date)}</p>
                  <small>{post.summary}</small>
                </span>
              </Link>
            ))}
          </div>
        )}
        {status === 'ready' && (
          <Pagination page={data.page} pages={data.pages} onChange={(n) => { setPage(n); window.scrollTo(0, 0) }} />
        )}
      </section>
    </main>
  )
}

export function PostPhoto({ post, main = false }) {
  const [failed, setFailed] = useState(false)
  if (!post.has_photo || failed) {
    return <span className={main ? 'post-detail-empty' : 'post-thumb'}>사진 없음</span>
  }
  // 분실 신고 사진은 공공데이터 사진 주소(photo_url)를 바로 쓰고, 회원 글 사진은 우리 서버에서 받는다.
  return (
    <img
      className={main ? undefined : 'post-thumb post-thumb-img'}
      src={post.photo_url || API_BASE + postPhotoPath(post.id)}
      alt={`${postTitle(post).replace(' 찾습니다', '')} 사진`}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  )
}

function PostForm({ regions, onCancel, onCreated }) {
  const toast = useToast()
  const [form, setForm] = useState(EMPTY)
  const [location, setLocation] = useState(null)
  const [regionOpen, setRegionOpen] = useState(false)
  const [photo, setPhoto] = useState(null)
  const [errors, setErrors] = useState({})
  const [photoError, setPhotoError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState(null)
  const firstField = useRef(null)
  const today = localDate()

  useEffect(() => {
    firstField.current?.focus()
  }, [])

  function update(field) {
    return (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }))
  }

  async function choosePhoto(event) {
    const file = event.target.files?.[0]
    setPhotoError('')
    if (!file) {
      setPhoto(null)
      return
    }
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
      setPhoto(null)
      setPhotoError('JPG·PNG·WebP 사진만 올릴 수 있어요.')
      return
    }
    try {
      const resized = await shrinkImage(file)
      if (dataUrlBytes(resized) > MAX_PHOTO_BYTES) throw new Error('too_large')
      setPhoto(resized)
    } catch {
      setPhoto(null)
      setPhotoError('사진을 줄이지 못했어요. 다른 사진을 골라 주세요.')
    }
  }

  async function submit(event) {
    event.preventDefault()
    const found = validatePost(form, today)
    setErrors(found)
    setServerError(null)
    if (Object.keys(found).length) return
    setSubmitting(true)
    try {
      const body = { ...form, photo: photo || undefined }
      const post = await api('/posts', { method: 'POST', body })
      toast('게시글을 등록했어요.')
      onCreated(post)
    } catch (err) {
      setServerError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="panel post-form" onSubmit={submit} noValidate>
      <div className="panel-title">
        <span aria-hidden="true">＋</span>
        <h2>새 실종 정보 등록</h2>
      </div>
      <div className="post-form-grid">
        <label>
          반려동물 이름
          <input ref={firstField} value={form.pet_name} onChange={update('pet_name')} placeholder="예: 초코" maxLength={20} aria-invalid={!!errors.pet_name} />
          <FieldError text={errors.pet_name} />
        </label>
        <label>
          동물 종류
          <select value={form.species} onChange={update('species')} aria-invalid={!!errors.species}>
            <option value="">선택</option>
            {POST_SPECIES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <FieldError text={errors.species} />
        </label>
        <div className="field-block">
          <span className="field-label">실종 위치</span>
          <button
            type="button"
            className={`region-trigger${location ? ' filled' : ''}`}
            onClick={() => setRegionOpen(true)}
            aria-haspopup="dialog"
            aria-invalid={!!errors.region}
            disabled={!regions.list.length}
          >
            <span aria-hidden="true">⌖</span>
            {location ? location.address || location.region : regions.error ? '지역 목록을 불러오지 못했어요' : '지도에서 실종 위치 선택'}
          </button>
          <FieldError text={errors.region} />
        </div>
        <label>
          실종 날짜
          <input type="date" value={form.lost_date} max={today} onChange={update('lost_date')} aria-invalid={!!errors.lost_date} />
          <FieldError text={errors.lost_date} />
        </label>
        <label>
          품종 (선택)
          <input value={form.breed} onChange={update('breed')} placeholder="예: 푸들, 코리안 숏헤어" maxLength={30} />
          <FieldError text={errors.breed} />
        </label>
        <label>
          사진 (선택)
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={choosePhoto} />
          {photo && <img className="post-photo-preview" src={photo} alt="선택한 사진 미리보기" />}
          <FieldError text={photoError} />
        </label>
        <label className="wide">
          특징과 마지막으로 본 장소
          <textarea rows={4} value={form.description} onChange={update('description')} placeholder="털 색, 크기, 목줄, 마지막으로 본 장소를 적어주세요." maxLength={1000} aria-invalid={!!errors.description} />
          <FieldError text={errors.description} />
        </label>
      </div>
      {serverError && (
        <p className="state-box state-error" role="alert">{errorMessage(serverError)}</p>
      )}
      <RegionPicker
        open={regionOpen}
        regions={regions.list}
        initial={location}
        allowAll={false}
        title="실종 위치 선택"
        onClose={() => setRegionOpen(false)}
        onSelect={(value) => {
          // 게시글에는 주소만 저장하고 선택한 정확한 좌표는 저장하지 않는다.
          setLocation(value)
          setForm((prev) => ({
            ...prev,
            region: value.region,
            lost_place: value.address && value.address !== value.region ? value.address : ''
          }))
          setRegionOpen(false)
        }}
      />
      <div className="form-bottom">
        <p className="fineprint">
          게시글은 로그인하지 않은 사람도 볼 수 있어요. 연락처·주소 같은 개인정보는 적지 마세요. 내가 쓴 글은 상세 화면에서 지울 수 있어요.
        </p>
        <div>
          <button type="button" className="secondary-button" onClick={onCancel} disabled={submitting}>취소</button>
          <button type="submit" className="primary-button" disabled={submitting}>{submitting ? '등록 중…' : '게시글 등록'}</button>
        </div>
      </div>
    </form>
  )
}

function FieldError({ text }) {
  return text ? <small className="field-error" role="alert">{text}</small> : null
}

async function shrinkImage(file) {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = reject
      el.src = url
    })
    const scale = Math.min(1, 1024 / Math.max(img.naturalWidth, img.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale))
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height)
    for (const quality of [0.85, 0.75, 0.6, 0.45]) {
      const out = canvas.toDataURL('image/jpeg', quality)
      if (dataUrlBytes(out) <= MAX_PHOTO_BYTES) return out
    }
    throw new Error('too_large')
  } finally {
    URL.revokeObjectURL(url)
  }
}
