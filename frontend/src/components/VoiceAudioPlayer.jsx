import { useRef, useState } from 'react'
import { API_BASE } from '../lib/api.js'

export default function VoiceAudioPlayer({ postId, voiceId }) {
  const source = `${API_BASE}/posts/${encodeURIComponent(postId)}/voices/${encodeURIComponent(voiceId)}/audio`
  const audioRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState('')

  async function togglePlayback() {
    const audio = audioRef.current
    if (!audio) return
    setError('')
    if (audio.paused) {
      try {
        await audio.play()
        setPlaying(true)
      } catch {
        setError('음성을 재생하지 못했어요. 잠시 후 다시 시도해 주세요.')
      }
    } else {
      audio.pause()
      setPlaying(false)
    }
  }

  function seek(event) {
    const time = Number(event.target.value)
    if (!audioRef.current || !Number.isFinite(time)) return
    audioRef.current.currentTime = time
    setCurrentTime(time)
  }

  function updateDuration(event) {
    const value = event.currentTarget.duration
    if (Number.isFinite(value)) setDuration(value)
  }

  return (
    <div className="voice-player-frame" role="group" aria-label="음성 재생기">
      <audio
        ref={audioRef}
        className="voice-audio-source"
        preload="metadata"
        src={source}
        tabIndex={-1}
        aria-hidden="true"
        onLoadedMetadata={updateDuration}
        onDurationChange={updateDuration}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => setError('음성 파일을 불러오지 못했어요.')}
      />
      <button type="button" className="voice-play-button" onClick={togglePlayback} aria-label={playing ? '일시정지' : '재생'}>
        <span aria-hidden="true">{playing ? 'Ⅱ' : '▶'}</span>
      </button>
      <div className="voice-playback-track">
        <input
          className="voice-seek"
          type="range"
          min="0"
          max={duration || 0}
          step="0.1"
          value={Math.min(currentTime, duration || 0)}
          onChange={seek}
          aria-label="재생 위치"
          disabled={!duration}
          style={{ '--voice-progress': `${duration ? (currentTime / duration) * 100 : 0}%` }}
        />
        <span className="voice-time" aria-live="off">{formatTime(currentTime)} / {formatTime(duration)}</span>
      </div>
      {error && <p className="voice-player-error" role="status">{error}</p>}
    </div>
  )
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const whole = Math.floor(seconds)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}
