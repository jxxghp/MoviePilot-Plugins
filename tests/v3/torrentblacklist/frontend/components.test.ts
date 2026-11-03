import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import Config from '../../../../plugins.v3/torrentblacklist/src/components/Config.vue'
import Page from '../../../../plugins.v3/torrentblacklist/src/components/Page.vue'

const global = () => ({ plugins: [createVuetify({ components })] })
const ok = (data: unknown) => ({ success: true, message: '', data })
const site = { id: 7, name: '测试站' }
const rules = { rules: [], total: 0, revision: 0, capacity: 1000 }
const item = { id: 8, title: '电影', torrent_name: 'Film.2026.CAM', torrent_site: '测试站',
  date: '2026-01-01', can_block: true, blocked: false, unavailable_reason: null }
function mockApi() {
  return {
    get: vi.fn(async (url: string) => ok(url.endsWith('/sites') ? { sites: [site] }
      : url.endsWith('/history') ? { items: [item], total: 1 } : rules)),
    post: vi.fn(async () => ok({ created: true, rule: { id: 'abc' }, revision: 1 })),
    delete: vi.fn(async () => ok({ deleted: true, revision: 2 })),
  }
}
function page(api = mockApi()) {
  render(Page, { props: { api, pluginId: 'TorrentBlacklistClone2', sourcePluginId: 'TorrentBlacklist' }, global: global() })
  return api
}

describe('真实 Vuetify 配置交互', () => {
  it('checkbox only updates a local draft and saves through host emit', async () => {
    const original = { enabled: false }
    const view = render(Config, { props: { initialConfig: original }, global: global() })
    const user = userEvent.setup()
    await user.click(screen.getByRole('checkbox', { name: '启用种子黑名单' }))
    expect(original.enabled).toBe(false)
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(view.emitted().save).toEqual([[{ enabled: true }]])
  })
})

describe('管理页面', () => {
  it('uses runtime plugin ID and adds literal keyword then refreshes', async () => {
    const api = page()
    await screen.findByText('暂无黑名单规则')
    const user = userEvent.setup()
    await user.type(screen.getByRole('textbox', { name: '关键词' }), '[[CAM].*')
    await user.click(screen.getByRole('button', { name: '添加关键词' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('plugin/TorrentBlacklistClone2/rules',
      { kind: 'keyword', keyword: '[CAM].*', site_id: null }, { feedback: 'silent' }))
    expect(api.get.mock.calls.every(([url]) => url.startsWith('plugin/TorrentBlacklistClone2/'))).toBe(true)
    await waitFor(() => expect((screen.getByRole('textbox', { name: '关键词' }) as HTMLInputElement).value).toBe(''))
  })

  it('retains user input and displays resolved failure envelopes', async () => {
    const api = mockApi()
    api.post.mockResolvedValue({ success: false, message: '规则已满', data: null } as never)
    page(api)
    await screen.findByText('暂无黑名单规则')
    await fireEvent.update(screen.getByRole('textbox', { name: '关键词' }), 'CAM')
    await fireEvent.click(screen.getByRole('button', { name: '添加关键词' }))
    await screen.findByText('规则已满')
    expect((screen.getByRole('textbox', { name: '关键词' }) as HTMLInputElement).value).toBe('CAM')
  })

  it('adds a site rule using selected numeric ID', async () => {
    const api = page()
    await screen.findByText('暂无黑名单规则')
    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: '屏蔽站点' }))
    await user.click(await screen.findByRole('option', { name: '测试站' }))
    await user.click(screen.getByRole('button', { name: '添加站点' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('plugin/TorrentBlacklistClone2/rules',
      { kind: 'site', site_id: 7 }, { feedback: 'silent' }))
  })

  it('blocks history with ID only and displays already-added state', async () => {
    const api = page()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: '下载历史' }))
    await screen.findByText('Film.2026.CAM')
    api.get.mockImplementation(async (url: string) => ok(url.endsWith('/history')
      ? { items: [{ ...item, blocked: true }], total: 1 } : url.endsWith('/sites') ? { sites: [site] } : rules))
    await user.click(screen.getByRole('button', { name: '屏蔽同站同名种子' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('plugin/TorrentBlacklistClone2/history/8/block',
      undefined, { feedback: 'silent' }))
    expect((await screen.findByRole('button', { name: '已添加' })).hasAttribute('disabled')).toBe(true)
  })

  it('shows unavailable history facts, empty states and capacity', async () => {
    const api = mockApi()
    api.get.mockImplementation(async (url: string) => ok(url.endsWith('/history')
      ? { items: [{ ...item, can_block: false, unavailable_reason: '缺少完整标题' }], total: 1 }
      : url.endsWith('/sites') ? { sites: [] } : { ...rules, total: 1000 }))
    page(api)
    await screen.findByText(/已达到.*1000.*规则上限/)
    expect(screen.getByRole('button', { name: '添加关键词' }).hasAttribute('disabled')).toBe(true)
    await fireEvent.click(screen.getByRole('tab', { name: '下载历史' }))
    await screen.findByText('缺少完整标题')
    expect(screen.getByRole('button', { name: '无法添加' }).hasAttribute('disabled')).toBe(true)
  })

  it('deletes the rule and refreshes the list', async () => {
    const api = mockApi()
    api.get.mockImplementation(async (url: string) => ok(url.endsWith('/sites') ? { sites: [] }
      : { ...rules, rules: [{ id: 'abc', kind: 'keyword', keyword: 'cam' }], total: 1 }))
    page(api)
    await fireEvent.click(await screen.findByRole('button', { name: '删除规则' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('plugin/TorrentBlacklistClone2/rules/abc', { feedback: 'silent' }))
  })

  it('keeps the latest history search when an older request finishes later', async () => {
    const api = mockApi()
    let oldResolve: (value: unknown) => void = () => {}
    api.get.mockImplementation(async (url: string, options?: any) => {
      if (!url.endsWith('/history')) return ok(url.endsWith('/sites') ? { sites: [] } : rules)
      if (options.params.search === 'old') return new Promise(resolve => { oldResolve = resolve }) as never
      return ok({ items: [{ ...item, torrent_name: options.params.search === 'new' ? 'NEW result' : 'initial' }], total: 1 })
    })
    page(api)
    await fireEvent.click(screen.getByRole('tab', { name: '下载历史' }))
    await screen.findByText('initial')
    const input = screen.getByRole('textbox', { name: '搜索媒体标题或下载路径' })
    await fireEvent.update(input, 'old')
    await fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(api.get.mock.calls.some(([url, options]: any) => url.endsWith('/history') && options.params.search === 'old')).toBe(true))
    await fireEvent.update(input, 'new')
    await fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await screen.findByText('NEW result')
    oldResolve(ok({ items: [{ ...item, torrent_name: 'OLD result' }], total: 1 }))
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(screen.queryByText('OLD result')).toBeNull()
    expect(screen.getByText('NEW result')).toBeTruthy()
  })
})

it('requests distinct bounded pages for rules and history and resets search to first page', async () => {
  const api = mockApi()
  api.get.mockImplementation(async (url: string, options?: any) => ok(url.endsWith('/sites') ? { sites: [] }
    : url.endsWith('/history') ? { items: [{ ...item, torrent_name: `history-page-${options.params.page}` }], total: 41 }
    : { ...rules, total: 41, rules: [{ id: 'abc', kind: 'keyword', keyword: `rule-page-${options.params.page}` }] }))
  page(api)
  await screen.findByText('关键词：rule-page-1')
  await fireEvent.click(screen.getByRole('button', { name: '下一页规则' }))
  await screen.findByText('关键词：rule-page-2')
  await fireEvent.click(screen.getByRole('tab', { name: '下载历史' }))
  await screen.findByText('history-page-1')
  await fireEvent.click(screen.getByRole('button', { name: '下一页历史' }))
  await screen.findByText('history-page-2')
  await fireEvent.update(screen.getByRole('textbox', { name: '搜索媒体标题或下载路径' }), 'new')
  await fireEvent.click(screen.getByRole('button', { name: '搜索' }))
  await screen.findByText('history-page-1')
  expect(api.get).toHaveBeenLastCalledWith('plugin/TorrentBlacklistClone2/history', {
    feedback: 'silent', params: { page: 1, page_size: 20, search: 'new' },
  })
})

it('shows retryable load errors and preserves site selection after rejected writes', async () => {
  const api = mockApi()
  api.get.mockImplementation(async (url: string) => {
    if (url.endsWith('/history')) throw new Error('历史暂时不可用')
    return ok(url.endsWith('/sites') ? { sites: [site] } : rules)
  })
  api.post.mockRejectedValue(new Error('连接失败'))
  page(api)
  await screen.findByText('暂无黑名单规则')
  const user = userEvent.setup()
  await user.click(screen.getByRole('combobox', { name: '屏蔽站点' }))
  await user.click(await screen.findByRole('option', { name: '测试站' }))
  await user.click(screen.getByRole('button', { name: '添加站点' }))
  await screen.findByText('连接失败')
  expect(screen.getByRole('button', { name: '添加站点' }).hasAttribute('disabled')).toBe(false)
  await user.click(screen.getByRole('button', { name: '添加站点' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
  expect(api.post).toHaveBeenLastCalledWith('plugin/TorrentBlacklistClone2/rules', { kind: 'site', site_id: 7 }, { feedback: 'silent' })
  await user.click(screen.getByRole('tab', { name: '下载历史' }))
  await screen.findByText('历史暂时不可用')
  api.get.mockResolvedValue(ok({ items: [], total: 0 }))
  await user.click(screen.getByRole('button', { name: '重试历史' }))
  await screen.findByText('暂无匹配的下载历史')
})
