export interface Envelope<T> { success: boolean; message: string; data: T | null }
export interface Api {
  get<T>(url: string, options?: { params?: Record<string, string | number>; feedback: 'silent' }): Promise<Envelope<T>>
  post<T>(url: string, data?: unknown, options?: { feedback: 'silent' }): Promise<Envelope<T>>
  delete<T>(url: string, options?: { feedback: 'silent' }): Promise<Envelope<T>>
}
export interface Rule {
  id: string; kind: 'keyword' | 'site' | 'site_title'; keyword?: string | null
  site_id?: number | null; site_name?: string | null; title?: string | null
}
export interface RulePage { rules: Rule[]; total: number; revision: number; capacity: number }
export interface HistoryItem {
  id: number; title: string | null; torrent_name: string | null; torrent_site: string | null
  date: string | null; can_block: boolean; blocked: boolean; unavailable_reason: string | null
}
export interface HistoryPage { items: HistoryItem[]; total: number }
export interface Site { id: number; name: string }
export function unwrap<T>(response: Envelope<T>): T {
  if (!response.success || response.data == null) throw new Error(response.message || '操作失败，请重试')
  return response.data
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}
