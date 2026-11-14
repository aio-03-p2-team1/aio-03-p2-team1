import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Header from './components/Header.jsx'
import Footer from './components/Footer.jsx'
import { ToastProvider } from './components/Toast.jsx'
import { useAuth } from './lib/auth.jsx'
import { SearchViewProvider } from './lib/searchView.jsx'
import BoardPage from './pages/BoardPage.jsx'
import DetailPage from './pages/DetailPage.jsx'
import SearchPage from './pages/SearchPage.jsx'
import AuthPage from './pages/AuthPage.jsx'
import MyPage from './pages/MyPage.jsx'
import PostBoardPage from './pages/PostBoardPage.jsx'
import PostDetailPage from './pages/PostDetailPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'

function RequireLogin({ children }) {
  const { user, ready } = useAuth()
  const location = useLocation()
  if (!ready) return <main className="page-main"><p className="state-box">로그인 상태를 확인하고 있어요…</p></main>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  return children
}

export default function App() {
  const { user } = useAuth()
  return (
    <ToastProvider>
      <Header />
      <SearchViewProvider key={user?.email || 'guest'}>
      <Routes>
        <Route path="/" element={<BoardPage />} />
        <Route path="/notices/:noticeId" element={<DetailPage />} />
        <Route
          path="/search"
          element={
            <RequireLogin>
              {/* 계정이 바뀌면 이전 계정의 화면 상태를 초기화한다 */}
              <SearchPage key={user?.email || 'guest'} />
            </RequireLogin>
          }
        />
        <Route
          path="/my"
          element={
            <RequireLogin>
              <MyPage key={user?.email || 'guest'} />
            </RequireLogin>
          }
        />
        {/* 실종 정보 게시판: 읽기는 공개, 등록은 화면 안에서 로그인 확인 */}
        <Route path="/board" element={<PostBoardPage />} />
        {/* 공공데이터 분실 신고 상세(회원 글과 같은 화면, 주소만 구분) */}
        <Route path="/board/lost/:lostId" element={<PostDetailPage />} />
        <Route path="/board/:postId" element={<PostDetailPage />} />
        <Route path="/login" element={<AuthPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      </SearchViewProvider>
      <Footer />
    </ToastProvider>
  )
}
