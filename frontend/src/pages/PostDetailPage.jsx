import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDate, formatDateTime } from '../lib/format.js'
import { isLostReport, localDate, postSpeciesLabel, postTitle, sexLabel } from '../lib/post.js'
import { createPosterFromTemplate, posterPayload } from '../lib/posterDocument.js'
import { fillPoster, postToPosterFields, setPosterPhoto } from '../lib/postPoster.js'
import { postToSearch, savePostSearch } from '../lib/postSearch.js'
import PostComments from '../components/PostComments.jsx'
import PostVoices from '../components/PostVoices.jsx'
import { useToast } from '../components/Toast.jsx'
import { PostPhoto } from './PostBoardPage.jsx'

// 회원 글(/board/:postId)과 공공데이터 분실 신고(/board/lost/:lostId)를 같은 화면으로 보여 준다.
export default function PostDetailPage() {
  const { postId, lostId } = useParams()
  const apiPath = lostId ? `/posts/lost/${encodeURIComponent(lostId)}` : `/posts/${encodeURIComponent(postId)}`
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const [post, setPost] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [editing, setEditing] = useState(false)
  const [reload, setReload] = useState(0)
  const [makingPoster, setMakingPoster] = useState(false)

  useEffect(() => {
    setStatus('loading')
    api(apiPath, { auth: false })
      .then((data) => {
        setPost(data)
        setStatus('ready')
        document.title = `다시 만나 · ${postTitle(data)}`
      })
      .catch((err) => {
        setError(err)
        setStatus('error')
      })
  }, [apiPath, user, reload])

  // 이 글의 종류·위치·날짜·특징으로 검색 화면을 채운다(바로 검색하지 않음, 로그인이 필요하면 로그인 후 이어짐).
  function searchWithPost() {
    savePostSearch(postToSearch(post, localDate()))
    navigate('/search')
  }

  // 게시글 정보로 기본 템플릿 전단지를 만들어 저장한 뒤 전단지 상세로 간다. 연락처는 사용자가 수정 화면에서 넣는다.
  async function makePoster() {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(window.location.pathname)}`)
      return
    }
    setMakingPoster(true)
    try {
      const template = await api('/poster/templates/basic')
      let poster = fillPoster(createPosterFromTemplate(template), postToPosterFields(post))
      const assetId = post.has_photo ? await uploadPostPhoto(post) : null
      if (assetId) poster = setPosterPhoto(poster, assetId)
      const created = await api('/posters', { method: 'POST', body: posterPayload(poster) })
      toast(post.has_photo && !assetId ? '전단지를 만들었어요. 사진은 가져오지 못해 직접 넣어 주세요.' : '전단지를 만들었어요. 연락처를 넣어 완성해 주세요.')
      navigate(`/posters/${encodeURIComponent(created.id)}`)
    } catch (err) {
      toast(err?.code === 'poster_limit' ? '전단지는 5개까지 저장할 수 있어요. 마이페이지에서 기존 전단지를 지운 뒤 다시 만들어 주세요.' : errorMessage(err))
      setMakingPoster(false)
    }
  }

  async function remove() {
    setDeleting(true)
    try {
      await api(`/posts/${encodeURIComponent(postId)}`, { method: 'DELETE' })
      toast('게시글을 지웠어요.')
      navigate('/board')
    } catch (err) {
      setError(err)
      setDeleting(false)
      setConfirming(false)
      toast(errorMessage(err))
    }
  }

  if (status === 'loading') {
    return <main className="page-main post-detail-page"><p className="state-box">게시글을 불러오고 있어요…</p></main>
  }
  if (status === 'error') {
    return (
      <main className="page-main post-detail-page">
        <div className="panel detail-not-found">
          <h1>게시글을 찾지 못했어요.</h1>
          <p>{error?.code === 'post_not_found' ? '지워졌거나 없는 게시글이에요.' : errorMessage(error)}</p>
          <Link className="primary-button" to="/board">게시판으로 돌아가기</Link>
        </div>
      </main>
    )
  }

  const lost = isLostReport(post)
  return (
    <main className="page-main post-detail-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span>
        <Link to="/board">실종 정보 게시판</Link><span aria-hidden="true">›</span><span>상세</span>
      </div>
      <div className="detail-heading">
        <div>
          {post.mine && <span className="sample-label">내 글</span>}
          <h1>{postTitle(post)}</h1>
          <p>{lost ? '공공데이터 분실 신고' : '실종 정보 게시판'} · {post.region}</p>
        </div>
        <div className="post-detail-heading-actions">
          {post.mine && (
            <div className="post-owner-actions">
              {!editing && !confirming && <button type="button" className="secondary-button" onClick={() => setEditing(true)}>게시글 수정</button>}
              {editing && <button type="button" className="secondary-button" onClick={() => setEditing(false)}>수정 취소</button>}
              {!confirming && <button type="button" className="secondary-button danger-button" onClick={() => { setEditing(false); setConfirming(true) }}>게시글 삭제</button>}
              {confirming && (
                <>
                  <button type="button" className="primary-button danger-button" onClick={remove} disabled={deleting}>{deleting ? '삭제 중…' : '삭제 확인'}</button>
                  <button type="button" className="secondary-button" onClick={() => setConfirming(false)} disabled={deleting}>취소</button>
                </>
              )}
            </div>
          )}
          <Link className="text-link" to="/board">← 게시판으로</Link>
        </div>
      </div>
      <div className="post-detail-layout">
        <div className="post-detail-media">
          <PostPhoto post={post} main />
          <p>{!post.has_photo ? '사진이 없는 게시글이에요.' : lost ? '분실 신고에 등록된 사진이에요.' : '작성자가 올린 사진이에요.'}</p>
        </div>
        <section className="detail-information" aria-label="실종 정보">
          <div className="detail-status">
            <span className="sample-label">실종</span>
            {post.created_at && <span>등록 {formatDateTime(post.created_at)}</span>}
          </div>
          {lost ? (
            // 분실 신고: 신고자·연락처·칩 번호·상세 주소는 서버에서 이미 빠져 있다.
            <dl className="detail-facts">
              <Fact label="종류" value={postSpeciesLabel(post.species)} />
              <Fact label="품종" value={post.breed} />
              <Fact label="색" value={post.color} />
              <Fact label="성별" value={sexLabel(post.sex)} />
              <Fact label="나이" value={post.age} />
              <Fact label="분실 지역" value={post.region} />
              <Fact label="분실 주소" value={post.lost_place} />
              <Fact label="분실 장소" value={post.happen_place} />
              <Fact label="분실 날짜" value={formatDate(post.lost_date)} />
            </dl>
          ) : (
            <dl className="detail-facts">
              <Fact label="이름" value={post.pet_name} />
              <Fact label="종류" value={postSpeciesLabel(post.species)} />
              <Fact label="품종" value={post.breed} />
              <Fact label="실종 지역" value={post.region} />
              <Fact label="실종 위치" value={post.lost_place} />
              <Fact label="실종 날짜" value={formatDate(post.lost_date)} />
            </dl>
          )}
          <div className="detail-copy">
            <h2>{lost ? '특징' : '특징과 마지막으로 본 장소'}</h2>
            <p className="post-description">{post.description}</p>
          </div>
          <div className="detail-page-actions">
            <button type="button" className="primary-button" onClick={searchWithPost}>이 정보로 구조 공고 찾기</button>
            {post.mine && (
              // 내가 쓴 글에만 보인다(분실 신고는 mine 이 항상 false).
              <button type="button" className="secondary-button" onClick={makePoster} disabled={makingPoster}>
                {makingPoster ? '전단지 만드는 중…' : '전단지 만들기'}
              </button>
            )}
          </div>
          <p className="fineprint">
            {lost
              ? '출처: 국가동물보호정보시스템 분실 신고(공공데이터포털). 개인정보(신고자·연락처 등)는 표시하지 않아요.'
              : '작성자가 직접 올린 정보예요. 보호소 공고가 아니며, 내용은 다시 만나가 확인하지 않았어요.'}
          </p>
        </section>
      </div>
      {editing && post.mine && <PostEditForm post={post} onSaved={() => { setEditing(false); setReload((n) => n + 1) }} />}
      {!lost && <PostVoices post={post} editable={editing} onChanged={() => setReload((n) => n + 1)} />}
      <PostComments key={post.id} targetId={post.id} lostReport={lost} />
    </main>
  )
}

// 게시글 사진을 서버가 전단지 자산으로 복사한다. 분실 신고 사진은 외부 주소라 브라우저가 직접 읽지 못해(CORS) 서버를 거친다.
// 실패하면 사진 없이 전단지를 만들고 사용자에게 알린다.
async function uploadPostPhoto(post) {
  try {
    const { assetId } = await api('/poster/assets/from-post', { method: 'POST', body: { postId: post.id } })
    return assetId
  } catch {
    return null
  }
}

function PostEditForm({ post, onSaved }) {
  const [form, setForm] = useState({
    pet_name: post.pet_name, species: post.species, region: post.region, lost_place: post.lost_place || '',
    lost_date: post.lost_date, breed: post.breed || '', description: post.description
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  function change(key) { return (event) => setForm((prev) => ({ ...prev, [key]: event.target.value })) }
  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api(`/posts/${encodeURIComponent(post.id)}`, { method: 'PATCH', body: form })
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="panel post-edit-form" onSubmit={submit}>
      <h2>게시글 수정</h2>
      <div className="post-edit-grid">
        <label>반려동물 이름<input value={form.pet_name} maxLength={20} onChange={change('pet_name')} required /></label>
        <label>동물 종류<select value={form.species} onChange={change('species')}><option value="dog">개</option><option value="cat">고양이</option><option value="etc">기타</option></select></label>
        <label>시·도<input value={form.region} maxLength={20} onChange={change('region')} required /></label>
        <label>실종 위치<input value={form.lost_place} maxLength={100} onChange={change('lost_place')} /></label>
        <label>실종 날짜<input type="date" value={form.lost_date} max={localDate()} onChange={change('lost_date')} required /></label>
        <label>품종<input value={form.breed} maxLength={30} onChange={change('breed')} /></label>
        <label className="wide">특징<textarea value={form.description} minLength={5} maxLength={1000} onChange={change('description')} required /></label>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="form-bottom"><span className="fineprint">현재 사진과 음성은 유지됩니다.</span><div><button type="submit" className="primary-button" disabled={busy}>{busy ? '저장 중…' : '수정 저장'}</button></div></div>
    </form>
  )
}

function Fact({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || '미입력'}</dd>
    </div>
  )
}
