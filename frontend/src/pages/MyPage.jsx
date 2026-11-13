import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDate, formatDateTime, paginate, runStatusLabel, runSummary, sourceLabel } from '../lib/format.js'
import { postSpeciesLabel, postTitle } from '../lib/post.js'
import { useToast } from '../components/Toast.jsx'

const HISTORY_LIMIT = 50
const PAGE_SIZE = 5

function useList(path, pick) {
  const [state, setState] = useState({ status: 'loading', items: [], error: null })
  function load() {
    setState((s) => ({ ...s, status: 'loading' }))
    api(path)
      .then((body) => setState({ status: 'ready', items: pick(body), error: null }))
      .catch((error) => setState({ status: 'error', items: [], error }))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])
  return { ...state, reload: load }
}

export default function MyPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const runs = useList(`/runs?limit=${HISTORY_LIMIT}`, (b) => b.runs)
  const posts = useList('/posts/mine', (b) => b.items)
  const [page, setPage] = useState(1)

  useEffect(() => {
    document.title = '다시 만나 · 마이페이지'
  }, [])

  async function onLogout() {
    await logout()
    toast('로그아웃했어요.')
    navigate('/')
  }

  const latest = runs.items[0]
  const completed = runs.items.filter((r) => r.status === 'completed' || r.status === 'partial').length
  const shown = paginate(runs.items, page, PAGE_SIZE)

  return (
    <main className="page-main my-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>마이페이지</span>
      </div>
      <div className="page-heading">
        <span className="eyebrow">나의 다시 만나</span>
        <h1>마이페이지</h1>
        <p>내 정보와 검색 기록, 내가 쓴 실종 정보 게시글을 볼 수 있어요. 검색 기록은 내 계정에만 저장돼요.</p>
      </div>

      <section className="panel my-dashboard" aria-labelledby="dashboard-title">
        <div className="mini-heading">
          <div><span className="eyebrow">나의 활동</span><h2 id="dashboard-title">요약</h2></div>
        </div>
        <div className="mini-items">
          <div><span>최근 검색</span><strong>{latest ? runSummary(latest.criteria) : '기록 없음'}</strong></div>
          <div><span>검색 기록</span><strong>{runs.status === 'ready' ? `${runs.items.length}건${runs.items.length >= HISTORY_LIMIT ? ' 이상' : ''}` : '—'}</strong></div>
          <div><span>결과를 받은 검색</span><strong>{runs.status === 'ready' ? `${completed}건` : '—'}</strong></div>
          <div><span>내가 쓴 게시글</span><strong>{posts.status === 'ready' ? `${posts.items.length}개` : '—'}</strong></div>
        </div>
      </section>

      <div className="my-layout">
        <section className="panel profile-panel" aria-labelledby="profile-title">
          <div className="panel-title"><span>01</span><h2 id="profile-title">내 정보</h2></div>
          <div className="profile-avatar" aria-hidden="true">{user?.name?.slice(0, 1)}</div>
          <h3>{user?.name}</h3>
          <p>{user?.email}</p>
          <dl className="profile-facts">
            <div><dt>이름</dt><dd>{user?.name}</dd></div>
            <div><dt>이메일</dt><dd>{user?.email}</dd></div>
          </dl>
          <div className="profile-actions">
            <Link className="secondary-button" to="/search">우리 아이 찾기</Link>
            <button type="button" className="text-action" onClick={onLogout}>로그아웃</button>
          </div>
        </section>

        <div className="my-content">
          <section className="panel my-history-panel" aria-labelledby="my-history-title">
            <div className="my-section-head">
              <div><span className="eyebrow">다시 찾아보기</span><h2 id="my-history-title">검색 기록</h2></div>
              <Link className="text-link" to="/search">새 검색 ↗</Link>
            </div>
            <ListState list={runs} empty="아직 검색 기록이 없어요. 우리 아이 찾기에서 검색해 보세요." loading="검색 기록을 불러오고 있어요…" />
            {runs.status === 'ready' && runs.items.length > 0 && (
              <>
                <ul className="my-list my-run-list">
                  {shown.items.map((r) => (
                    <li key={r.run_id}>
                      <Link to={`/search?run=${encodeURIComponent(r.run_id)}`}>
                        <strong>{runSummary(r.criteria)}</strong>
                        <span>
                          <em className={`run-status run-status-${r.status}`}>{runStatusLabel(r.status)}</em>
                          {' '}후보 {r.candidate_count}마리 · 판단 수정 {r.reflection_count ?? 0}회 · {sourceLabel(r.data_source)} · {formatDateTime(r.created_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
                <Pager page={shown.page} pages={shown.pages} onChange={setPage} label="검색 기록 페이지" />
              </>
            )}
          </section>

          <section className="panel my-posts-panel" aria-labelledby="my-posts-title">
            <div className="my-section-head">
              <div><span className="eyebrow">실종 정보 게시판</span><h2 id="my-posts-title">내가 쓴 게시글</h2></div>
              <Link className="text-link" to="/board">게시판 가기 ↗</Link>
            </div>
            <ListState list={posts} empty="아직 쓴 게시글이 없어요. 실종 정보 게시판에서 우리 아이를 알려 보세요." loading="게시글을 불러오고 있어요…" />
            {posts.status === 'ready' && posts.items.length > 0 && (
              <ul className="my-list my-run-list">
                {posts.items.map((p) => (
                  <li key={p.id}>
                    <Link to={`/board/${encodeURIComponent(p.id)}`}>
                      <strong>{postTitle(p)}</strong>
                      <span>
                        {postSpeciesLabel(p.species)}{p.breed ? ` · ${p.breed}` : ''} · {p.region} · 실종 {formatDate(p.lost_date)} · 등록 {formatDateTime(p.created_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  )
}

function ListState({ list, empty, loading }) {
  if (list.status === 'loading') return <p className="my-empty">{loading}</p>
  if (list.status === 'error') {
    return (
      <p className="my-empty" role="alert">
        {errorMessage(list.error)} <button type="button" className="text-action" onClick={list.reload}>다시 시도</button>
      </p>
    )
  }
  if (list.items.length === 0) return <p className="my-empty">{empty}</p>
  return null
}

function Pager({ page, pages, onChange, label }) {
  if (pages <= 1) return null
  return (
    <nav className="my-pager" aria-label={label}>
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="이전 페이지">‹</button>
      {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
        <button key={n} type="button" className={n === page ? 'current' : ''} aria-current={n === page ? 'page' : undefined} onClick={() => onChange(n)}>
          {n}
        </button>
      ))}
      <button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="다음 페이지">›</button>
    </nav>
  )
}
