import { useState } from 'react'
import { noticeTitle } from '../lib/format.js'

/**
 * 공고 사진. 실제 공고는 API 사진 URL, 샘플 공고는 디자인 예시 이미지(스프라이트)를 쓴다.
 * variant: 'thumb'(게시판 카드) | 'notice'(검색 결과 카드, 390:171) | 'main'(상세)
 * src: 보여 줄 사진 URL(상세에서 고른 썸네일). 없으면 첫 사진.
 */
export default function NoticePhoto({ item, variant = 'thumb', src: selected }) {
  const src = selected || item?.photos?.[0]
  const [failedSrc, setFailedSrc] = useState(null)
  const failed = failedSrc === src
  const label = `${noticeTitle(item)} 사진`
  if (item?.source === 'sample' && item?.sample_photo != null) {
    const cls = variant === 'main' ? 'detail-main-photo' : variant === 'notice' ? 'notice-photo' : 'post-thumb sample-photo'
    return <span className={`${cls} photo-${item.sample_photo} sample-${item.sample_photo}`} role="img" aria-label={`${label} (샘플)`} />
  }
  if (!src || failed) {
    return <span className={variant === 'main' ? 'post-detail-empty' : 'post-thumb'}>사진 없음</span>
  }
  return (
    <img
      className={variant === 'main' ? 'detail-photo-img' : variant === 'notice' ? 'notice-photo notice-photo-img' : 'post-thumb post-thumb-img'}
      src={src}
      alt={label}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailedSrc(src)}
    />
  )
}
