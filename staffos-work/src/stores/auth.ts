/**
 * Auth store: token + identity, persisted to localStorage under the
 * `xian_` namespace (separate from the console's keys).
 */
import { create } from "zustand";
import { clearToken, getToken, setToken } from "../api/request";

interface AuthState {
  token: string;
  username: string;
  signIn: (token: string, username: string) => void;
  signOut: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: getToken(),
  username: localStorage.getItem("xian_username") ?? "",
  signIn: (token, username) => {
    setToken(token);
    localStorage.setItem("xian_username", username);
    set({ token, username });
  },
  signOut: () => {
    clearToken();
    localStorage.removeItem("xian_username");
    set({ token: "", username: "" });
  },
}));
