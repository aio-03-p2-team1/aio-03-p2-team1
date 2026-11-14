import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/auth.jsx'
import { errorMessage } from '../lib/format.js'

export default function AuthPage() {
  const [params] = useSearchParams()
  const [tab, setTab] = useState(params.get('tab') === 'signup' ? 'signup' : 'login')
  const { user, expired } = useAuth()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))

  useEffect(() => {
    document.title = '다시 만나 · 로그인'
  }, [])

  useEffect(() => {
    if (user) navigate(next, { replace: true })
  }, [user, next, navigate])

  return (
    <main className="page-main auth-page">
      <div className="breadcrumb">
        <Link to="/">메인</Link><span aria-hidden="true">›</span><span>로그인 · 회원가입</span>
      </div>
      <div className="auth-layout">
        <section className="auth-intro" aria-label="다시 만나 소개">
          <span className="eyebrow">다시 만나, 함께 찾는 기록</span>
          <h1>다시 만날 순간까지<br />함께할게요.</h1>
          <p>로그인하면 검색 기록과 후보 비교 결과를 이어서 확인할 수 있어요.</p>
          <div className="auth-symbol" aria-hidden="true"><span></span><span></span></div>
          <small>노란색과 회색의 두 마음이 다시 만나는 공간</small>
        </section>
        <section className="panel auth-card" aria-labelledby="auth-title">
          <div className="auth-tabs" role="tablist" aria-label="계정 메뉴">
            <button type="button" role="tab" aria-selected={tab === 'login'} onClick={() => setTab('login')}>로그인</button>
            <button type="button" role="tab" aria-selected={tab === 'signup'} onClick={() => setTab('signup')}>회원가입</button>
          </div>
          {expired && tab === 'login' && <p className="auth-error" role="alert">로그인이 만료되었어요. 다시 로그인해 주세요.</p>}
          {tab === 'login' ? <LoginForm onSwitch={() => setTab('signup')} /> : <SignupForm onSwitch={() => setTab('login')} />}
          <p className="auth-note">
            비밀번호는 서버에서 Argon2로 해시해 저장하고, 로그인 상태는 HttpOnly 쿠키로 유지해요.{' '}
            <Link className="text-link" to="/">홈으로 돌아가기</Link>
          </p>
        </section>
      </div>
    </main>
  )
}

function safeNext(value) {
  // 로그인 후 외부 주소로 이동하지 않도록 한다.
  return value && value.startsWith('/') && !value.startsWith('//') ? value : '/'
}

function PasswordInput({ id, value, onChange, autoComplete, placeholder }) {
  const [visible, setVisible] = useState(false)
  return (
    <span className="password-field">
      <input id={id} type={visible ? 'text' : 'password'} value={value} onChange={onChange} autoComplete={autoComplete} placeholder={placeholder} required />
      <button type="button" className="password-toggle" onClick={() => setVisible((v) => !v)} aria-pressed={visible} aria-label={visible ? '비밀번호 숨기기' : '비밀번호 보기'}>
        {visible ? '숨기기' : '보기'}
      </button>
    </span>
  )
}

function LoginForm({ onSwitch }) {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function onSubmit(event) {
    event.preventDefault()
    setError('')
    if (!email.trim() || !password) return setError('이메일과 비밀번호를 입력해 주세요.')
    setBusy(true)
    try {
      await login(email.trim(), password)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="tabpanel">
      <h2 id="auth-title">다시 오신 걸 환영해요</h2>
      <p className="auth-subtitle">가입한 이메일과 비밀번호로 로그인해 주세요.</p>
      <form className="auth-form" onSubmit={onSubmit} noValidate>
        <label>이메일<input type="email" autoComplete="email" placeholder="example@email.com" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>비밀번호<PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" placeholder="비밀번호" /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" className="primary-button" disabled={busy}>{busy ? '로그인 중…' : '로그인'}</button>
      </form>
      <p className="auth-switch">아직 계정이 없나요? <button type="button" onClick={onSwitch}>회원가입</button></p>
    </div>
  )
}

function SignupForm({ onSwitch }) {
  const { register } = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function onSubmit(event) {
    event.preventDefault()
    setError('')
    if (!name.trim() || !email.trim()) return setError('이름과 이메일을 입력해 주세요.')
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return setError('이메일 형식을 확인해 주세요.')
    if (password.length < 8) return setError('비밀번호는 8자 이상 입력해 주세요.')
    if (password !== confirm) return setError('비밀번호 확인이 일치하지 않아요.')
    setBusy(true)
    try {
      await register(name.trim(), email.trim(), password)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="tabpanel">
      <h2 id="auth-title">처음 오셨나요?</h2>
      <p className="auth-subtitle">간단한 정보를 입력하고 시작해 주세요.</p>
      <form className="auth-form" onSubmit={onSubmit} noValidate>
        <label>이름<input autoComplete="nickname" maxLength={30} placeholder="예: 보리 보호자" value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label>이메일<input type="email" autoComplete="email" maxLength={254} placeholder="example@email.com" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>비밀번호<PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" placeholder="8자 이상" /></label>
        <label>비밀번호 확인<PasswordInput value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" placeholder="비밀번호 다시 입력" /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" className="primary-button" disabled={busy}>{busy ? '가입 중…' : '회원가입'}</button>
      </form>
      <p className="auth-switch">이미 계정이 있나요? <button type="button" onClick={onSwitch}>로그인</button></p>
    </div>
  )
}
