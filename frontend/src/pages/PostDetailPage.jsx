import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDate, formatDateTime } from '../lib/format.js'
import { isLostReport, postSpeciesLabel, postTitle, sexLabel } from '../lib/post.js'
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
  }, [apiPath, user])

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
        <Link className="text-link" to="/board">← 게시판으로</Link>
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
          <p className="fineprint">
            {lost
              ? '출처: 국가동물보호정보시스템 분실 신고(공공데이터포털). 개인정보(신고자·연락처 등)는 표시하지 않아요.'
              : '작성자가 직접 올린 정보예요. 보호소 공고가 아니며, 내용은 다시 만나가 확인하지 않았어요.'}
          </p>
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
