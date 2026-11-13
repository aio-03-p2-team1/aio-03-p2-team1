import { useState } from 'react'
import { noticeTitle } from '../lib/format.js'

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
