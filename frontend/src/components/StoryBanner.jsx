import sceneOne from '../assets/story-wide-1.jpg'
import sceneTwo from '../assets/story-wide-2.jpg'
import sceneThree from '../assets/story-wide-3.jpg'
import sceneFour from '../assets/story-wide-4.jpg'

const scenes = [sceneOne, sceneTwo, sceneThree, sceneFour]

export default function StoryBanner() {
  return (
    <section className="home-story" aria-label="다시 만나는 이야기">
      <div
        className="home-story-stage"
        role="img"
        aria-label="회색 점과 노란 점이 만나고, 다시마를 든 너구리가 리트리버를 찾아 재회하는 이야기"
      >
        <div className="home-story-dots" aria-hidden="true">
          <span className="home-story-dot home-story-dot-gray" />
          <span className="home-story-dot home-story-dot-yellow" />
          <span className="home-story-merged" />
          <span className="home-story-bloom" />
        </div>
        {scenes.map((src, index) => (
          <img
            key={src}
            className={`home-story-scene home-story-scene-${index + 1}`}
            src={src}
            alt=""
            draggable="false"
            loading="eager"
          />
        ))}
      </div>
    </section>
  )
}
