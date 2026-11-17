import { useState } from 'react'
import { api } from '../lib/api.js'
import { errorMessage } from '../lib/format.js'
import PostVoiceCard from './PostVoiceCard.jsx'

const MAX_VOICES = 3
const MAX_BYTES = 10 * 1024 * 1024
const ACCEPT = 'audio/mpeg,audio/mp4,audio/wav,audio/x-wav,audio/ogg,audio/opus,.mp3,.m4a,.wav,.ogg,.opus'

export default function PostVoices({ post, editable = false, onChanged }) {
  const [file, setFile] = useState(null)
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const voices = post.voices || []

  function choose(event) {
    const selected = event.target.files?.[0] || null
    setError('')
    if (selected && selected.size > MAX_BYTES) {
      setFile(null)
      setError('음성 파일은 하나당 10 MiB까지 올릴 수 있어요.')
    } else setFile(selected)
  }

  async function add(event) {
    event.preventDefault()
    if (!file || !description.trim() || busy) return
    const form = event.currentTarget
    const data = new FormData()
    data.append('audio', file)
    data.append('description', description.trim())
    setBusy(true)
    setError('')
    try {
      await api(`/posts/${encodeURIComponent(post.id)}/voices`, { method: 'POST', body: data })
      setFile(null)
      setDescription('')
      form.reset()
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(voiceId) {
    setBusy(true)
    setError('')
    try {
      await api(`/posts/${encodeURIComponent(post.id)}/voices/${encodeURIComponent(voiceId)}`, { method: 'DELETE' })
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel post-voices" aria-labelledby="post-voices-title">
      <h2 id="post-voices-title">목소리와 음성 기록</h2>
      {voices.length === 0 && <p className="fineprint">등록된 음성 파일이 없어요.</p>}
      <ul className="voice-list">
        {voices.map((voice) => (
          <PostVoiceCard key={voice.id} postId={post.id} voice={voice} editable={post.mine && editable} busy={busy} onRemove={remove} />
        ))}
      </ul>
      {post.mine && editable && voices.length < MAX_VOICES && (
        <form className="voice-form" onSubmit={add}>
          <label>음성 파일 <input type="file" accept={ACCEPT} onChange={choose} /></label>
          <label>음성 설명 <input value={description} maxLength={200} onChange={(e) => setDescription(e.target.value)} placeholder="예: 초코가 부르면 반응하는 이름" /></label>
          <p className="fineprint">MP3·M4A·WAV·OGG, 1분 이내, 파일당 10 MiB까지. 최대 3개예요.</p>
          {error && <p className="field-error" role="alert">{error}</p>}
          <button type="submit" className="secondary-button" disabled={busy || !file || !description.trim()}>{busy ? '처리 중…' : '음성 추가'}</button>
        </form>
      )}
      {error && <p className="field-error" role="alert">{error}</p>}
    </section>
  )
}
