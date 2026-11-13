import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDate, formatDateTime } from '../lib/format.js'
import { postSpeciesLabel, postTitle } from '../lib/post.js'
import { useToast } from '../components/Toast.jsx'
import { PostPhoto } from './PostBoardPage.jsx'

// 실종 정보 상세 — 디자인: dasimanna-cards-post-detail.html
export default function PostDetailPage() {
  const { postId } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const [post, setPost] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    setStatus('loading')
    api(`/posts/${encodeURIComponent(postId)}`, { auth: false })
      .then((data) => {
        setPost(data)
        setStatus('ready')
        document.title = `다시 만나 · ${postTitle(data)}`
      })
      .catch((err) => {
        setError(err)
        setStatus('error')
      })
  }, [postId, user])

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
          <p>실종 정보 게시판 · {post.region}</p>
        </div>
        <Link className="text-link" to="/board">← 게시판으로</Link>
      </div>
      <div className="post-detail-layout">
        <div className="post-detail-media">
          <PostPhoto post={post} main />
          <p>{post.has_photo ? '작성자가 올린 사진이에요.' : '사진이 없는 게시글이에요.'}</p>
        </div>
        <section className="detail-information" aria-label="실종 정보">
          <div className="detail-status">
            <span className="sample-label">실종</span>
            <span>등록 {formatDateTime(post.created_at)}</span>
          </div>
          <dl className="detail-facts">
            <Fact label="이름" value={post.pet_name} />
            <Fact label="종류" value={postSpeciesLabel(post.species)} />
            <Fact label="품종" value={post.breed} />
            <Fact label="실종 지역" value={post.region} />
            <Fact label="실종 날짜" value={formatDate(post.lost_date)} />
          </dl>
          <div className="detail-copy">
            <h2>특징과 마지막으로 본 장소</h2>
            <p className="post-description">{post.description}</p>
          </div>
          <div className="detail-page-actions">
            <Link className="secondary-button" to="/board">게시판 목록</Link>
            {post.mine && !confirming && (
              <button type="button" className="secondary-button danger-button" onClick={() => setConfirming(true)}>게시글 삭제</button>
            )}
            {post.mine && confirming && (
              <>
                <button type="button" className="primary-button danger-button" onClick={remove} disabled={deleting}>
                  {deleting ? '지우는 중…' : '정말 지울게요'}
                </button>
                <button type="button" className="secondary-button" onClick={() => setConfirming(false)} disabled={deleting}>취소</button>
              </>
            )}
          </div>
          <p className="fineprint">작성자가 직접 올린 정보예요. 보호소 공고가 아니며, 내용은 다시 만나가 확인하지 않았어요.</p>
        </section>
      </div>
    </main>
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
