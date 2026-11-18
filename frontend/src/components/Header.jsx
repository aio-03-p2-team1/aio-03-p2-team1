import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { shouldReloadOnNav } from '../lib/nav.js'
import { useAuth } from '../lib/auth.jsx'
import { useToast } from './Toast.jsx'

export default function Header() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()

  // 지금 보고 있는 페이지의 로고·메뉴를 누르면 새로고침해 처음 상태로 돌아간다(검색 결과·입력값 초기화).
  function refreshIfCurrent(to) {
    return (event) => {
      if (!shouldReloadOnNav(location.pathname, to, event)) return
      event.preventDefault()
      window.location.assign(to)
    }
  }

  async function onLogout() {
    await logout()
    toast('로그아웃했어요.')
    navigate('/')
  }

  return (
    <header className="site-header">
      <Link className="brand" to="/" onClick={refreshIfCurrent('/')}>
        <img className="brand-icon" src="/brand-icon.png" alt="" width="40" height="40" />
        <span className="brand-wordmark">다시 만나</span>
      </Link>
      <nav aria-label="주요 메뉴">
        <NavLink to="/" end onClick={refreshIfCurrent('/')}>전체 공고</NavLink>
        <NavLink to="/search" onClick={refreshIfCurrent('/search')}>우리 아이 찾기</NavLink>
        <NavLink to="/board" onClick={refreshIfCurrent('/board')}>실종 정보 게시판</NavLink>
        <NavLink to="/poster" onClick={refreshIfCurrent('/poster')}>전단지 만들기</NavLink>
        <NavLink to="/my" onClick={refreshIfCurrent('/my')}>마이페이지</NavLink>
        {/* 관리자 계정에만 보인다. 권한 확인은 서버가 /admin/* 요청마다 다시 한다 */}
        {user?.is_admin && <NavLink to="/admin" onClick={refreshIfCurrent('/admin')}>관리자</NavLink>}
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
