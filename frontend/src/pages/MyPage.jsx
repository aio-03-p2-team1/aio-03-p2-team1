import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage, formatDateTime, runStatusLabel, runSummary, sourceLabel } from '../lib/format.js'
import { useToast } from '../components/Toast.jsx'

const HISTORY_LIMIT = 50

// 마이페이지 — 디자인: dasimanna-cards-my.html (내 정보 · 검색 기록)
export default function MyPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const [runs, setRuns] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  function load() {
    setStatus('loading')
    api(`/runs?limit=${HISTORY_LIMIT}`)
      .then((body) => {
        setRuns(body.runs)
        setStatus('ready')
      })
      .catch((err) => {
        setError(err)
        setStatus('error')
      })
  }

  useEffect(() => {
    document.title = '다시 만나 · 마이페이지'
    load()
  }, [])

  async function onLogout() {
    await logout()
    toast('로그아웃했어요.')
    navigate('/')
  }

  const latest = runs[0]
  const completed = runs.filter((r) => r.status === 'completed' || r.status === 'partial').length

  return (
    <main className="page-main my-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>마이페이지</span>
      </div>
      <div className="page-heading">
        <span className="eyebrow">나의 다시 만나</span>
        <h1>마이페이지</h1>
        <p>내 정보와 우리 아이 찾기 검색 기록을 볼 수 있어요. 기록은 내 계정에만 저장돼요.</p>
      </div>

      <section className="panel my-dashboard" aria-labelledby="dashboard-title">
        <div className="mini-heading">
          <div><span className="eyebrow">나의 활동</span><h2 id="dashboard-title">요약</h2></div>
        </div>
        <div className="mini-items">
          <div><span>최근 검색</span><strong>{latest ? runSummary(latest.criteria) : '기록 없음'}</strong></div>
          <div><span>검색 기록</span><strong>{status === 'ready' ? `${runs.length}건${runs.length >= HISTORY_LIMIT ? ' 이상' : ''}` : '—'}</strong></div>
          <div><span>결과를 받은 검색</span><strong>{status === 'ready' ? `${completed}건` : '—'}</strong></div>
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
            {status === 'loading' && <p className="my-empty">검색 기록을 불러오고 있어요…</p>}
            {status === 'error' && (
              <p className="my-empty" role="alert">
                {errorMessage(error)} <button type="button" className="text-action" onClick={load}>다시 시도</button>
              </p>
            )}
            {status === 'ready' && runs.length === 0 && (
              <p className="my-empty">아직 검색 기록이 없어요. 우리 아이 찾기에서 검색해 보세요.</p>
            )}
            {status === 'ready' && runs.length > 0 && (
              <ul className="my-list my-run-list">
                {runs.map((r) => (
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
            )}
          </section>
        </div>
      </div>
    </main>
  )
}
