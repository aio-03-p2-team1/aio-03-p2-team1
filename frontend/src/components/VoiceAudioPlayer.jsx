import { API_BASE } from '../lib/api.js'

export default function VoiceAudioPlayer({ postId, voiceId }) {
  const source = `${API_BASE}/posts/${encodeURIComponent(postId)}/voices/${encodeURIComponent(voiceId)}/audio`
  return (
    <div className="voice-player-frame">
      <audio controls preload="none" src={source} aria-label="음성 파일 재생" />
    </div>
  )
}
