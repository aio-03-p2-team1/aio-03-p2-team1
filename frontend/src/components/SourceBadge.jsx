import { sourceLabel } from '../lib/format.js'

export default function SourceBadge({ source }) {
  return <span className={`sample-label source-${source || 'unknown'}`}>{sourceLabel(source)}</span>
}
