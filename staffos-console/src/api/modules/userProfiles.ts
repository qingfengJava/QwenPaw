/**
 * User profile batch lookup — resolves user ids into display-safe
 * profiles (display name + avatar) for list surfaces (run logs, etc.).
 *
 * Backend: GET /api/users/profiles?usernames=a,b,c — one request per
 * batch (never per-row); unknown usernames are silently omitted.
 */
import { request } from "../request";

/** Display-safe profile of one account (no password/role/org fields). */
export interface UserProfile {
  username: string;
  display_name: string;
  /** Custom avatar URL; empty = caller renders a DiceBear fallback. */
  avatar: string;
}

/** Backend caps one batch; stay under it so nothing is silently dropped. */
const MAX_BATCH = 200;

export const userProfilesApi = {
  /**
   * Resolve a batch of usernames into profiles.
   * Returns a Map keyed by username for O(1) row rendering.
   */
  getProfiles: async (usernames: string[]): Promise<Map<string, UserProfile>> => {
    const unique = [...new Set(usernames.filter(Boolean))].slice(0, MAX_BATCH);
    if (unique.length === 0) {
      return new Map();
    }
    const items = await request<UserProfile[]>(
      `/users/profiles?usernames=${encodeURIComponent(unique.join(","))}`,
    );
    const map = new Map<string, UserProfile>();
    for (const item of items || []) {
      map.set(item.username, item);
    }
    return map;
  },
};
