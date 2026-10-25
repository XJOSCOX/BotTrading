import { useSyncExternalStore } from "react";
import { api, establish, type Json } from "./api";
let data: Json = {
  profiles: {},
  monitor: [],
  alerts: [],
  events: [],
  prices: {},
  connected: false,
};
const listeners = new Set<() => void>();
function update(patch: Json) {
  data = { ...data, ...patch };
  listeners.forEach((listener) => listener());
}
export function useLive() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => data,
  );
}
export async function refresh() {
  update(await api("/snapshot"));
}
export function connect() {
  let socket: WebSocket | undefined,
    timer: ReturnType<typeof setTimeout>,
    stopped = false,
    delay = 1000;
  const open = async () => {
    try {
      await establish();
      if (stopped) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/stream`,
      );
      socket.onopen = () => {
        delay = 1000;
        update({ connected: true, error: null });
        window.dispatchEvent(new Event("gox-connected"));
      };
      socket.onmessage = (event) => {
        const frame = JSON.parse(event.data);
        update(frame.data);
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        update({ connected: false });
        if (!stopped) {
          timer = setTimeout(open, delay);
          delay = Math.min(15000, delay * 2);
        }
      };
    } catch (error) {
      update({ connected: false, error: String(error) });
      if (!stopped) timer = setTimeout(open, 5000);
    }
  };
  void open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}
