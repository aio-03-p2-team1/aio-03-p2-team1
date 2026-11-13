import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth.jsx'
import { useToast } from './Toast.jsx'

export default function Header() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()

  async function onLogout() {
    await logout()
    toast('로그아웃했어요.')
    navigate('/')
  }

  return (
    <header className="site-header">
      <Link className="brand" to="/">
        <span className="brand-paw" aria-hidden="true">●<i>● ● ●</i></span> 다시 만나
      </Link>
      <nav aria-label="주요 메뉴">
        <NavLink to="/" end>전체 공고</NavLink>
        <NavLink to="/search">우리 아이 찾기</NavLink>
        <NavLink to="/my">마이페이지</NavLink>
      </nav>
      {user ? (
        <div className="account-area">
          <Link className="account-name" to="/my">{user.name}님</Link>
          <button type="button" className="account-link" onClick={onLogout}>로그아웃</button>
        </div>
      ) : (
        <Link className="account-link" to="/login">로그인</Link>
      )}
    </header>
  )
}
