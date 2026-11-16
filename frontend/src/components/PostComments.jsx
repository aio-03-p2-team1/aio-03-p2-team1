import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDateTime } from '../lib/format.js'
import { useToast } from './Toast.jsx'

export const COMMENT_MAX = 500

/**
 * 실종 정보 게시판 댓글. 회원 글과 공공데이터 분실 신고 모두 게시글 ID(targetId)로 댓글을 묶는다.
 * 읽기는 누구나, 쓰기는 로그인한 사람만, 지우기는 작성자만 할 수 있다.
 */
export default function PostComments({ targetId, lostReport }) {
  const { user } = useAuth()
  const location = useLocation()
  const toast = useToast()
  const path = `/posts/${encodeURIComponent(targetId)}/comments`
  const [items, setItems] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [removing, setRemoving] = useState(null)

  function load() {
    setStatus('loading')
    api(path, { auth: false })
      .then((body) => {
        setItems(body.items)
        setStatus('ready')
      })
      .catch((err) => {
        setError(err)
        setStatus('error')
      })
  }

  // 게시글이 바뀌거나 로그인 상태가 바뀌면(내 댓글 표시) 다시 불러온다.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [path, user?.email])

  async function submit(event) {
    event.preventDefault()
    const body = text.trim()
    if (!body || sending) return
    setSending(true)
    try {
      const created = await api(path, { method: 'POST', body: { body } })
      setItems((list) => [...list, created])
      setText('')
    } catch (err) {
      toast(errorMessage(err))
    } finally {
      setSending(false)
    }
  }

  async function remove(id) {
    setRemoving(id)
    try {
      await api(`${path}/${encodeURIComponent(id)}`, { method: 'DELETE' })
      setItems((list) => list.filter((c) => c.id !== id))
      toast('댓글을 지웠어요.')
    } catch (err) {
      toast(errorMessage(err))
    } finally {
      setRemoving(null)
    }
  }

  return (
    <section className="panel post-comments" aria-labelledby="post-comments-title">
      <div className="post-comments-head">
        <h2 id="post-comments-title">댓글 {status === 'ready' ? <span>{items.length}</span> : null}</h2>
        <p className="fineprint">
          본 적이 있거나 도움이 될 정보를 남겨 주세요. 전화번호는 자동으로 가려져요.
          {lostReport && ' 분실 신고 원본이 수정되면 이전 댓글이 보이지 않을 수 있어요.'}
        </p>
      </div>

      {status === 'loading' && <p className="my-empty">댓글을 불러오고 있어요…</p>}
      {status === 'error' && (
        <p className="my-empty" role="alert">
          {errorMessage(error)} <button type="button" className="text-action" onClick={load}>다시 시도</button>
        </p>
      )}
      {status === 'ready' && items.length === 0 && <p className="my-empty">아직 댓글이 없어요. 첫 댓글을 남겨 주세요.</p>}
      {status === 'ready' && items.length > 0 && (
        <ul className="comment-list">
          {items.map((c) => (
            <li key={c.id} className={c.mine ? 'mine' : ''}>
              <div className="comment-meta">
                <strong>{c.author_name}</strong>
                {c.mine && <span className="sample-label">내 댓글</span>}
                <span>{formatDateTime(c.created_at)}</span>
                {c.mine && (
                  <button type="button" className="text-action" onClick={() => remove(c.id)} disabled={removing === c.id}>
                    {removing === c.id ? '지우는 중…' : '삭제'}
                  </button>
                )}
              </div>
              <p className="comment-body">{c.body}</p>
            </li>
          ))}
        </ul>
      )}

      {user ? (
        <form className="comment-form" onSubmit={submit}>
          <label className="sr-only" htmlFor="comment-input">댓글 입력</label>
          <textarea
            id="comment-input"
            rows={3}
            maxLength={COMMENT_MAX}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="언제, 어디서 봤는지 적어 주세요."
          />
          <div className="comment-form-foot">
            <span className="fineprint">{text.length}/{COMMENT_MAX}</span>
            <button type="submit" className="primary-button" disabled={sending || !text.trim()}>
              {sending ? '등록 중…' : '댓글 등록'}
            </button>
          </div>
        </form>
      ) : (
        <p className="comment-login">
          댓글을 쓰려면 <Link className="text-link" to={`/login?next=${encodeURIComponent(location.pathname)}`}>로그인</Link>해 주세요.
        </p>
      )}
    </section>
  )
}
