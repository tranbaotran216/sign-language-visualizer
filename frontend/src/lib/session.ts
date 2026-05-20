import { useEffect, useRef, useState } from "react";

const PREFIX = "kltn:";
const RESTORED_FLAG = "kltn:__restored_once__";

const writeTimers = new Map<string, number>();

export function loadState<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function saveState<T>(key: string, value: T) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // quota or unserializable; ignore silently
  }
}

export function debouncedSave<T>(key: string, value: T, delay = 250) {
  const t = writeTimers.get(key);
  if (t) window.clearTimeout(t);
  const id = window.setTimeout(() => {
    saveState(key, value);
    writeTimers.delete(key);
  }, delay);
  writeTimers.set(key, id);
}

/** A useState that mirrors to localStorage, debounced. */
export function usePersistedState<T>(key: string, initial: T): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [val, setVal] = useState<T>(() => loadState<T>(key, initial));
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    debouncedSave(key, val);
  }, [key, val]);
  return [val, setVal];
}

export function clearSession() {
  const keys: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(PREFIX)) keys.push(k);
  }
  keys.forEach(k => localStorage.removeItem(k));
}

export function hasPersistedSession(): boolean {
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(PREFIX) && k !== RESTORED_FLAG) return true;
  }
  return false;
}

export function markRestoredOnce(): boolean {
  // returns true if this is the first call in this tab session
  if (sessionStorage.getItem(RESTORED_FLAG)) return false;
  sessionStorage.setItem(RESTORED_FLAG, "1");
  return true;
}
