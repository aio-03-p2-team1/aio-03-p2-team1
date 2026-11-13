/** 성공적으로 폼에 반영된 사진 분석 결과에 대한 간단한 피드백 팝업. */
export default function PhotoFeedbackPopup({ feedback, onFeedback, onClose }) {
  return (
    <aside className="photo-feedback-popup" aria-label="사진 분석 결과 의견" aria-live="polite">
      <span className="photo-feedback-question">
        {feedback ? '피드백을 선택했어요. 감사합니다.' : '사진 분석 결과가 마음에 드나요?'}
      </span>
      <div className="photo-feedback-actions" aria-label="사진 분석 결과 피드백">
        <button
          type="button"
          className={feedback === 'like' ? 'selected' : ''}
          aria-pressed={feedback === 'like'}
          onClick={() => onFeedback('like')}
        >
          👍 좋아요
        </button>
        <button
          type="button"
          className={feedback === 'dislike' ? 'selected' : ''}
          aria-pressed={feedback === 'dislike'}
          onClick={() => onFeedback('dislike')}
        >
          👎 싫어요
        </button>
      </div>
      <button type="button" className="photo-feedback-close" aria-label="팝업 닫기" onClick={onClose}>×</button>
    </aside>
  )
}
