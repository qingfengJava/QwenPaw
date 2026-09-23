/**
 * FeedItem — prototype L716-776: avatar + meta line (actor + verb + date)
 * + feed-box. `boxIcon` follows the prototype (fa-regular fa-square-check
 * for items, fa-solid fa-comment for comments).
 */
import Avatar from "../Avatar";
import { pickColor } from "../Avatar";

export interface FeedItemView {
  id: number | string;
  actor: string;
  verb: string;
  target: string;
  boxIcon: string;
  wrapText?: boolean;
  createdAt?: string | null;
}

export default function FeedItem({ event }: { event: FeedItemView }) {
  return (
    <div className="feed-item">
      <Avatar
        name={event.actor}
        size={32}
        color={pickColor(event.actor)}
        className="feed-avatar"
      />
      <div className="feed-content">
        <div className="feed-meta">
          <div>
            <strong>{event.actor}</strong> <span>{event.verb}</span>
          </div>
          <span>{event.createdAt?.slice(0, 10) ?? ""}</span>
        </div>
        <div className={`feed-box${event.wrapText ? " wrap-text" : ""}`}>
          <i className={event.boxIcon} />
          <span>{event.target}</span>
        </div>
      </div>
    </div>
  );
}

export { pickColor };
