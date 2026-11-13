import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <main className="page-main">
      <div className="panel detail-not-found">
        <h1>페이지를 찾지 못했어요.</h1>
        <Link className="primary-button" to="/">메인으로</Link>
      </div>
    </main>
  )
}
