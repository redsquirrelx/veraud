export class LocalStorage {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = window.localStorage.getItem(key)
      if (raw === null) {
        return fallback
      }
      return JSON.parse(raw) as T
    } catch {
      return fallback
    }
  }

  set(key: string, value: unknown): void {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // storage unavailable (private mode, quota): keep the app running
    }
  }

  remove(key: string): void {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // ignore
    }
  }
}

export const localStorage = new LocalStorage()
