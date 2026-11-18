import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import {
  ADMIN_TABS, counterRows, downloadText, number, percent, runsToCsv, statLabel, tabFromSearch,
} from '../lib/admin.js'
import { errorMessage, formatDate, formatDateTime, runStatusLabel, runSummary } from '../lib/format.js'
import { postSpeciesLabel } from '../lib/post.js'
import { useToast } from '../components/Toast.jsx'

// 관리자 화면. 권한은 서버가 요청마다 확인한다(관리자가 아니면 403). 메뉴 숨김은 화면 편의일 뿐이다.

function useAdmin(path) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, status: 'loading' }))
    api(path)
      .then((data) => live && setState({ status: 'ready', data, error: null }))
      .catch((error) => live && setState({ status: 'error', data: null, error }))
    return () => {
      live = false
    }
  }, [path, tick])
  return { ...state, reload: () => setTick((n) => n + 1) }
}

function Loader({ q, children }) {
  if (q.status === 'loading' && !q.data) return <p className="state-box">불러오고 있어요…</p>
  if (q.status === 'error') {
    return (
      <p className="state-box" role="alert">
        {errorMessage(q.error)} <button type="button" className="text-action" onClick={q.reload}>다시 시도</button>
      </p>
    )
  }
  return children(q.data)
}

export default function AdminPage() {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const tab = tabFromSearch(location.search)

  useEffect(() => {
    document.title = '다시 만나 · 관리자'
  }, [])

  if (!user?.is_admin) {
    return (
      <main className="page-main">
        <p className="state-box" role="alert">관리자만 볼 수 있어요.</p>
      </main>
    )
  }

  return (
    <main className="page-main admin-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>관리자</span>
      </div>
      <div className="page-heading">
        <span className="eyebrow">운영</span>
        <h1>관리자</h1>
        <p>서비스 상태와 에이전트 실행 기록을 보고, 사용자와 콘텐츠를 관리해요.</p>
      </div>
      <nav className="admin-tabs" aria-label="관리자 메뉴">
        {ADMIN_TABS.map((t) => (
          <button key={t.id} type="button" className={t.id === tab ? 'current' : ''} aria-current={t.id === tab ? 'page' : undefined}
            onClick={() => navigate(`/admin?tab=${t.id}`)}>
            {t.label}
          </button>
        ))}
      </nav>
      {tab === 'overview' && <OverviewTab />}
      {tab === 'agent' && <AgentTab />}
      {tab === 'runs' && <RunsTab />}
      {tab === 'users' && <UsersTab />}
      {tab === 'posts' && <PostsTab />}
      {tab === 'comments' && <CommentsTab />}
      {tab === 'posters' && <PostersTab />}
      {tab === 'logs' && <LogsTab />}
    </main>
  )
}

function Section({ title, action, children }) {
  return (
    <section className="panel admin-section">
      <div className="admin-section-head"><h2>{title}</h2>{action}</div>
      {children}
    </section>
  )
}

function Badge({ on, children }) {
  return <span className={`admin-badge ${on ? 'on' : 'off'}`}>{children}</span>
}

function Tiles({ items }) {
  return (
    <div className="admin-tiles">
      {items.map(([label, value]) => (
        <div key={label}><span>{label}</span><strong>{value}</strong></div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------ 현황

const INTEGRATION_LABELS = {
  animal_api: '구조동물 API', lost_api: '분실동물 API', kakao: '카카오 로컬', feature_llm: '특징 추출 LLM',
  photo_llm: '사진 분석 LLM', embedder: '임베딩', search_agent: '검색 에이전트', search_cache: '조건 캐시', langsmith: 'LangSmith 추적',
}

function OverviewTab() {
  const q = useAdmin('/admin/overview')
  return (
    <Loader q={q}>
      {(d) => (
        <>
          <Section title="연결 상태" action={<button type="button" className="text-action" onClick={q.reload}>새로 고침</button>}>
            <Tiles items={[
              ['서버 시작', formatDateTime(d.started_at)],
              ['실행 모드', d.app_mode],
              ['저장소', `${d.storage_backend} ${d.checks.store.ok ? `· ${d.checks.store.ms}ms` : '· 연결 실패'}`],
              ['Redis', d.checks.redis.ok ? `정상 · ${d.checks.redis.ms}ms` : `연결 실패 (${d.checks.redis.error})`],
            ]} />
          </Section>
          <Section title="에이전트·외부 연동">
            <table className="admin-table">
              <thead><tr><th>항목</th><th>상태</th><th>모델·출처</th></tr></thead>
              <tbody>
                {Object.entries(d.integrations).map(([key, v]) => (
                  <tr key={key}>
                    <td>{INTEGRATION_LABELS[key] || key}</td>
                    <td><Badge on={v.on}>{v.on ? '켜짐' : '꺼짐'}</Badge></td>
                    <td>{v.model || v.source || v.project || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
          <Section title="버전·한도">
            <Tiles items={[
              ['특징 추출 프롬프트', d.versions.feature_prompt],
              ['에이전트 프롬프트', d.versions.agent_prompt],
              ['반경 규칙', d.versions.radius],
              ['성찰 최대', `${d.limits.max_reflections}회`],
              ['도구 호출 최대', `${d.limits.max_tool_calls}회`],
              ['에이전트 걸음·다시 찾기', `${d.limits.agent_max_steps} · ${d.limits.agent_max_reruns}`],
            ]} />
          </Section>
        </>
      )}
    </Loader>
  )
}

// ------------------------------------------------------------ 에이전트 분석

function CounterTable({ title, counter, empty = '기록 없음' }) {
  const rows = counterRows(counter)
  return (
    <div className="admin-counter">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="fineprint">{empty}</p> : (
        <ul>
          {rows.map((r) => (
            <li key={r.key}>
              <span className="admin-counter-label" title={r.key}>{r.label}</span>
              <span className="admin-bar" aria-hidden="true"><i style={{ width: `${Math.max(2, r.share * 100)}%` }} /></span>
              <strong>{r.count}</strong>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function AgentTab() {
  const [limit, setLimit] = useState(300)
  const q = useAdmin(`/admin/agent/stats?limit=${limit}`)
  const toast = useToast()

  async function exportData(kind) {
    try {
      const runs = await api('/admin/runs?limit=200')
      const stamp = new Date().toISOString().slice(0, 10)
      if (kind === 'csv') downloadText(`agent-runs-${stamp}.csv`, runsToCsv(runs.items), 'text/csv')
      else downloadText(`agent-data-${stamp}.json`, JSON.stringify({ stats: q.data, runs: runs.items }, null, 2), 'application/json')
    } catch (err) {
      toast(errorMessage(err))
    }
  }

  return (
    <Loader q={q}>
      {(d) => (
        <>
          <Section
            title="요약"
            action={
              <div className="admin-actions">
                <label className="fineprint">최근
                  <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                    {[100, 300, 500].map((n) => <option key={n} value={n}>{n}건</option>)}
                  </select>
                </label>
                <button type="button" className="secondary-button" onClick={() => exportData('csv')}>실행 내역 CSV</button>
                <button type="button" className="secondary-button" onClick={() => exportData('json')}>분석 데이터 JSON</button>
              </div>
            }
          >
            <Tiles items={[
              ['읽은 실행', number(d.scanned, '건')],
              ['그래프 실행', number(d.executed_runs, '건')],
              ['캐시 적중률', percent(d.cache_hit_rate)],
              ['평균 처리 시간', number(d.avg_elapsed_ms, 'ms')],
              ['확신 낮음 비율', percent(d.confidence.low_rate)],
              ['에이전트가 돈 실행', number(d.agent.runs, '건')],
            ]} />
            <p className="fineprint">
              캐시 적중 실행은 그래프를 돌지 않아 도구·성찰 집계에서 뺐어요. 실제 사용자 검색 기록을 그대로 집계한 값이에요.
              {d.malformed_runs > 0 && ` 지금과 저장 형식이 다른 예전 기록 ${d.malformed_runs}건은 형식이 맞지 않는 값을 비우고 집계했어요.`}
            </p>
          </Section>

          <Section title="성찰 켬/끔 비교 (시험 보고서 지표 원자료)">
            <table className="admin-table">
              <thead><tr><th>구분</th><th>실행</th><th>완료율</th><th>실패율</th><th>질문으로 끝남</th><th>평균 성찰</th><th>평균 재시도</th><th>평균 도구 호출</th></tr></thead>
              <tbody>
                {[['성찰 켬', d.reflection_compare.on], ['성찰 끔', d.reflection_compare.off]].map(([label, g]) => (
                  <tr key={label}>
                    <td>{label}</td><td>{g.runs}</td><td>{percent(g.completed_rate)}</td><td>{percent(g.failed_rate)}</td>
                    <td>{percent(g.awaiting_input_rate)}</td><td>{number(g.avg_reflection_count)}</td>
                    <td>{number(g.avg_retry_count)}</td><td>{number(g.avg_tool_calls)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="결과와 문제">
            <div className="admin-counters">
              <CounterTable title="종료 상태" counter={Object.fromEntries(Object.entries(d.status).map(([k, v]) => [runStatusLabel(k), v]))} />
              <CounterTable title="종료 이유" counter={d.end_reason} />
              <CounterTable title="오류 코드" counter={d.errors} />
              <CounterTable title="검증에서 찾은 문제" counter={d.issues} />
              <CounterTable title="성찰로 고친 문제" counter={d.reflections} />
              <CounterTable title="확신이 낮은 이유" counter={d.confidence.reasons} />
            </div>
          </Section>

          <Section title="도구 사용">
            <div className="admin-counters">
              <CounterTable title="도구 호출 수" counter={d.tool_use} />
              <CounterTable title="도구 실패 수" counter={d.tool_fail} />
            </div>
          </Section>

          <Section title="검색 에이전트 판단">
            <Tiles items={[
              ['평균 걸음', number(d.agent.avg_steps)],
              ['평균 다시 찾기', number(d.agent.avg_reruns)],
            ]} />
            <div className="admin-counters">
              <CounterTable title="판단 출처" counter={d.agent.source} />
              <CounterTable title="마지막 도구" counter={d.agent.final_tool} />
              <CounterTable title="고른 도구" counter={d.agent.tool_calls} />
              <CounterTable title="서버가 거부한 도구" counter={d.agent.rejected} />
              <CounterTable title="화면 요청" counter={d.agent.requests} />
            </div>
            <h3 className="admin-sub">거부된 도구 호출 예 (프롬프트 개선 자료)</h3>
            {d.agent.rejected_examples.length === 0 ? <p className="fineprint">거부된 호출이 없어요.</p> : (
              <table className="admin-table">
                <thead><tr><th>시간</th><th>도구</th><th>인자</th><th>거부 이유</th></tr></thead>
                <tbody>
                  {d.agent.rejected_examples.map((r, i) => (
                    <tr key={i}>
                      <td>{formatDateTime(r.at)}</td><td>{r.tool}</td>
                      <td><code>{JSON.stringify(r.args)}</code></td><td>{String(r.reason ?? '-')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </>
      )}
    </Loader>
  )
}

// ------------------------------------------------------------ 실행 내역

const PAGE = 50

function RunsTab() {
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState(null)
  const q = useAdmin(`/admin/runs?limit=${PAGE}&offset=${offset}`)
  const toast = useToast()

  async function remove(row) {
    if (!window.confirm('이 검색 기록을 지울까요? 되돌릴 수 없어요.')) return
    try {
      await api(`/admin/runs/${row.owner}/${row.id}`, { method: 'DELETE' })
      toast('검색 기록을 지웠어요.')
      setOpen(null)
      q.reload()
    } catch (err) {
      toast(errorMessage(err))
    }
  }

  return (
    <Loader q={q}>
      {(d) => (
        <Section title="에이전트 실행 내역 (검색 기록)" action={<button type="button" className="text-action" onClick={q.reload}>새로 고침</button>}>
          {d.items.length === 0 ? <p className="state-box">실행 기록이 없어요.</p> : (
            <div className="admin-scroll">
              <table className="admin-table admin-runs">
                <thead>
                  <tr><th>시간</th><th>사용자</th><th>조건</th><th>상태</th><th>성찰·재시도·도구</th><th>확신</th><th>에이전트</th><th>처리</th><th /></tr>
                </thead>
                <tbody>
                  {d.items.map((r) => (
                    <tr key={`${r.owner}-${r.id}`} className={open?.id === r.id ? 'selected' : ''}>
                      <td>{formatDateTime(r.created_at)}</td>
                      <td>{r.email || r.owner?.slice(0, 8)}</td>
                      <td>{runSummary(r.criteria)}</td>
                      <td><span className={`run-status run-status-${r.status}`}>{runStatusLabel(r.status)}</span>{r.error ? ` · ${r.error}` : ''}{r.malformed ? ' · 예전 형식' : ''}</td>
                      <td>{r.reflection_count} · {r.retry_count} · {r.tool_call_count}{r.reflection_enabled === false ? ' (성찰 끔)' : ''}</td>
                      <td>{r.confidence_low ? r.confidence_reasons.map(statLabel).join(', ') || '낮음' : '충분'}</td>
                      <td>{r.agent_source ? `${statLabel(r.agent_source)} → ${r.agent_final_tool || '-'} (다시 ${r.agent_reruns})` : '-'}</td>
                      <td>{r.cache_hit ? '캐시' : number(r.elapsed_ms, 'ms')}</td>
                      <td><button type="button" className="text-action" onClick={() => setOpen(open?.id === r.id ? null : r)}>{open?.id === r.id ? '닫기' : '자세히'}</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="my-pager">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹ 이전</button>
            <button type="button" disabled={d.items.length < PAGE} onClick={() => setOffset(offset + PAGE)}>다음 ›</button>
          </div>
          {open && <RunDetail row={open} onDelete={() => remove(open)} />}
        </Section>
      )}
    </Loader>
  )
}

function Json({ value }) {
  return <pre className="admin-json">{JSON.stringify(value ?? null, null, 2)}</pre>
}

function RunDetail({ row, onDelete }) {
  const q = useAdmin(`/admin/runs/${row.owner}/${row.id}`)
  return (
    <div className="admin-detail">
      <div className="admin-section-head">
        <h3>실행 {row.id.slice(0, 8)} · {row.email || '알 수 없는 사용자'}</h3>
        <button type="button" className="text-action danger" onClick={onDelete}>이 기록 지우기</button>
      </div>
      <Loader q={q}>
        {({ run }) => (
          <div className="admin-detail-grid">
            <div><h4>조건</h4><Json value={run.criteria} /></div>
            <div><h4>거친 노드</h4><p className="admin-trace">{(run.trace || []).join(' → ') || '-'}</p>
              <h4>확신 신호</h4><Json value={run.confidence} /></div>
            <div><h4>검증 문제 · 성찰</h4><Json value={{ issues: run.issues, reflections: run.reflections }} /></div>
            <div><h4>에이전트 기록</h4><Json value={run.agent_decision} /></div>
            <div><h4>도구 호출 ({(run.tool_calls || []).length})</h4><Json value={run.tool_calls} /></div>
            <div><h4>상위 후보 {run.top_candidates.length} / {run.candidate_count}</h4><Json value={run.top_candidates} /></div>
          </div>
        )}
      </Loader>
    </div>
  )
}

// ------------------------------------------------------------ 사용자

function UsersTab() {
  const q = useAdmin('/admin/users')
  const toast = useToast()

  async function toggle(u) {
    const next = !u.disabled
    if (!window.confirm(next ? `${u.email} 계정을 정지할까요? 정지하면 새로 로그인할 수 없어요.` : `${u.email} 계정 정지를 풀까요?`)) return
    try {
      await api(`/admin/users/${u.owner}`, { method: 'PATCH', body: { disabled: next } })
      toast(next ? '계정을 정지했어요.' : '계정 정지를 풀었어요.')
      q.reload()
    } catch (err) {
      toast(errorMessage(err))
    }
  }

  return (
    <Loader q={q}>
      {(d) => (
        <Section title={`사용자 ${d.count}명`}>
          <p className="fineprint">정지하면 새 로그인이 막혀요. 이미 로그인한 세션은 만료될 때까지 남아 있어요.</p>
          <div className="admin-scroll">
            <table className="admin-table">
              <thead><tr><th>이메일</th><th>이름</th><th>역할</th><th>가입</th><th>검색</th><th>게시글</th><th>상태</th><th /></tr></thead>
              <tbody>
                {d.items.map((u) => (
                  <tr key={u.owner}>
                    <td>{u.email}</td><td>{u.name}</td><td>{u.role === 'admin' ? '관리자' : '사용자'}</td>
                    <td>{formatDate(u.created_at)}</td><td>{u.runs}</td><td>{u.posts}</td>
                    <td><Badge on={!u.disabled}>{u.disabled ? '정지' : '정상'}</Badge></td>
                    <td>{u.role !== 'admin' && <button type="button" className="text-action" onClick={() => toggle(u)}>{u.disabled ? '정지 해제' : '정지'}</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </Loader>
  )
}

// ------------------------------------------------------------ 게시물·댓글·전단지

function useDelete(q, message) {
  const toast = useToast()
  return async (path, confirmText) => {
    if (!window.confirm(confirmText)) return
    try {
      await api(path, { method: 'DELETE' })
      toast(message)
      q.reload()
    } catch (err) {
      toast(errorMessage(err))
    }
  }
}

function PostsTab() {
  const q = useAdmin('/admin/posts')
  const remove = useDelete(q, '게시글을 지웠어요.')
  return (
    <Loader q={q}>
      {(d) => (
        <Section title={`회원 게시글 ${d.count}개`}>
          <p className="fineprint">공공데이터 분실 신고는 우리 DB 에 저장하지 않으므로 여기에 없어요. 글을 지우면 음성·댓글도 함께 지워져요.</p>
          <div className="admin-scroll">
            <table className="admin-table">
              <thead><tr><th>등록</th><th>이름</th><th>종류·품종</th><th>지역</th><th>실종일</th><th>작성자</th><th>사진·음성</th><th /></tr></thead>
              <tbody>
                {d.items.map((p) => (
                  <tr key={p.id}>
                    <td>{formatDateTime(p.created_at)}</td>
                    <td><Link className="text-link" to={`/board/${p.id}`}>{p.pet_name}</Link></td>
                    <td>{postSpeciesLabel(p.species)}{p.breed ? ` · ${p.breed}` : ''}</td>
                    <td>{p.region}</td><td>{formatDate(p.lost_date)}</td><td>{p.author.email || '-'}</td>
                    <td>{p.has_photo ? '사진' : '-'} · 음성 {p.voices}</td>
                    <td><button type="button" className="text-action danger" onClick={() => remove(`/admin/posts/${p.id}`, `'${p.pet_name}' 게시글을 지울까요? 음성·댓글도 함께 지워지고 되돌릴 수 없어요.`)}>삭제</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </Loader>
  )
}

function CommentsTab() {
  const q = useAdmin('/admin/comments')
  const remove = useDelete(q, '댓글을 지웠어요.')
  return (
    <Loader q={q}>
      {(d) => (
        <Section title={`댓글 ${d.count}개`}>
          <div className="admin-scroll">
            <table className="admin-table">
              <thead><tr><th>작성</th><th>내용</th><th>게시글</th><th>작성자</th><th /></tr></thead>
              <tbody>
                {d.items.map((c) => (
                  <tr key={`${c.post_id}-${c.id}`}>
                    <td>{formatDateTime(c.created_at)}</td>
                    <td className="admin-wrap">{c.body}</td>
                    <td><Link className="text-link" to={c.target_source === 'lost_api' ? `/board/lost/${c.post_id}` : `/board/${c.post_id}`}>{c.target_source === 'lost_api' ? '분실 신고' : '회원 글'}</Link></td>
                    <td>{c.author.email || '-'}</td>
                    <td><button type="button" className="text-action danger" onClick={() => remove(`/admin/comments/${c.post_id}/${c.id}`, '이 댓글을 지울까요? 되돌릴 수 없어요.')}>삭제</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </Loader>
  )
}

function PostersTab() {
  const q = useAdmin('/admin/posters')
  const remove = useDelete(q, '전단지를 지웠어요.')
  return (
    <Loader q={q}>
      {(d) => (
        <Section title={`전단지 ${d.count}개`}>
          <div className="admin-scroll">
            <table className="admin-table">
              <thead><tr><th>수정</th><th>제목</th><th>이름·장소</th><th>템플릿</th><th>작성자</th><th /></tr></thead>
              <tbody>
                {d.items.map((p) => (
                  <tr key={`${p.author.owner}-${p.id}`}>
                    <td>{formatDateTime(p.updated_at)}</td><td>{p.title || '실종 전단지'}</td>
                    <td>{[p.pet_name, p.lost_place].filter(Boolean).join(' · ') || '-'}</td><td>{p.template_name}</td>
                    <td>{p.author.email || '-'}</td>
                    <td><button type="button" className="text-action danger" onClick={() => remove(`/admin/posters/${p.author.owner}/${p.id}`, '이 전단지를 지울까요? 되돌릴 수 없어요.')}>삭제</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </Loader>
  )
}

// ------------------------------------------------------------ 로그

function LogsTab() {
  const [source, setSource] = useState('')
  const [level, setLevel] = useState('')
  const params = new URLSearchParams({ limit: '300', ...(source && { source }), ...(level && { level }) })
  const q = useAdmin(`/admin/logs?${params}`)
  return (
    <Section
      title="최근 로그"
      action={
        <div className="admin-actions">
          <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="로그 종류">
            <option value="">전체</option><option value="request">API 요청</option><option value="server">서버 로그</option>
          </select>
          <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="로그 수준">
            <option value="">모든 수준</option><option value="INFO">INFO</option><option value="WARNING">WARNING</option><option value="ERROR">ERROR</option>
          </select>
          <button type="button" className="secondary-button" onClick={q.reload}>새로 고침</button>
        </div>
      }
    >
      <Loader q={q}>
        {(d) => (
          <>
            <p className="fineprint">서버 메모리에 최근 {d.capacity}건만 보관해요. 서버가 다시 시작하면({formatDateTime(d.started_at)} 시작) 비워지고, 요청 주소의 쿼리·본문은 남기지 않아요.</p>
            {d.items.length === 0 ? <p className="state-box">로그가 없어요.</p> : (
              <ol className="admin-logs">
                {d.items.map((l) => (
                  <li key={l.seq} className={`lvl-${l.level.toLowerCase()}`}>
                    <time>{formatDateTime(l.at)}</time><b>{l.level}</b><span>{l.source}</span><code>{l.message}</code>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </Loader>
    </Section>
  )
}
