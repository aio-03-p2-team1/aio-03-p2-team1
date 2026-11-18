import VoiceAudioPlayer from './VoiceAudioPlayer.jsx'

export default function PostVoiceCard({ postId, voice, editable, busy, onRemove }) {
  return (
    <li className="post-voice-card">
      <p className="post-voice-description">{voice.description}</p>
      <VoiceAudioPlayer postId={postId} voiceId={voice.id} />
      {editable && (
        <button type="button" className="text-action post-voice-remove" disabled={busy} onClick={() => onRemove(voice.id)}>
          음성 삭제
        </button>
      )}
    </li>
  )
}
