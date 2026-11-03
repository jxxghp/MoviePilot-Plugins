<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Api, HistoryItem, HistoryPage, Rule, RulePage, Site } from '../types'
import { errorMessage, unwrap } from '../types'

const props = defineProps<{ api: Api; pluginId: string; sourcePluginId?: string }>()
const tab = ref('rules')
const ruleList = ref<Rule[]>([])
const sites = ref<Site[]>([])
const history = ref<HistoryItem[]>([])
const totalRules = ref(0)
const totalHistory = ref(0)
const capacity = ref(1000)
const rulePage = ref(1)
const historyPage = ref(1)
const pageSize = 20
const keyword = ref('')
const keywordSite = ref<number | null>(null)
const selectedSite = ref<number | null>(null)
const searchDraft = ref('')
const search = ref('')
const ruleError = ref('')
const historyError = ref('')
const sitesError = ref('')
const actionError = ref('')
const notice = ref('')
const loadingRules = ref(false)
const loadingHistory = ref(false)
const busy = ref(false)
const full = computed(() => totalRules.value >= capacity.value)
let ruleRequest = 0
let historyRequest = 0
let siteRequest = 0
let instance = 0
const url = (path: string) => `plugin/${props.pluginId}${path}`
const silent = { feedback: 'silent' as const }

async function loadRules() {
  const request = ++ruleRequest
  loadingRules.value = true
  ruleError.value = ''
  try {
    const data = unwrap(await props.api.get<RulePage>(url('/rules'), {
      ...silent, params: { page: rulePage.value, page_size: pageSize },
    }))
    if (request !== ruleRequest) return
    ruleList.value = data.rules
    totalRules.value = data.total
    capacity.value = data.capacity
    if (rulePage.value > 1 && !data.rules.length) {
      rulePage.value = Math.max(1, Math.ceil(data.total / pageSize))
      await loadRules()
    }
  } catch (error) {
    if (request === ruleRequest) ruleError.value = errorMessage(error)
  } finally {
    if (request === ruleRequest) loadingRules.value = false
  }
}
async function loadSites() {
  const request = ++siteRequest
  sitesError.value = ''
  try {
    const data = unwrap(await props.api.get<{ sites: Site[] }>(url('/sites'), silent))
    if (request === siteRequest) sites.value = data.sites
  } catch (error) {
    if (request === siteRequest) sitesError.value = errorMessage(error)
  }
}
async function loadHistory() {
  const request = ++historyRequest
  loadingHistory.value = true
  historyError.value = ''
  try {
    const data = unwrap(await props.api.get<HistoryPage>(url('/history'), {
      ...silent, params: { page: historyPage.value, page_size: pageSize, search: search.value },
    }))
    if (request !== historyRequest) return
    history.value = data.items
    totalHistory.value = data.total
  } catch (error) {
    if (request === historyRequest) historyError.value = errorMessage(error)
  } finally {
    if (request === historyRequest) loadingHistory.value = false
  }
}
async function mutate(action: () => Promise<unknown>, after: () => void = () => {}) {
  if (busy.value) return
  const current = instance
  busy.value = true
  actionError.value = ''
  notice.value = ''
  try {
    await action()
    if (current !== instance) return
    after()
    notice.value = '操作成功'
    await Promise.all([loadRules(), ...(tab.value === 'history' ? [loadHistory()] : [])])
  } catch (error) {
    if (current === instance) actionError.value = errorMessage(error)
  } finally {
    if (current === instance) busy.value = false
  }
}
function addKeyword() {
  if (!keyword.value.trim() || full.value) return
  return mutate(async () => unwrap(await props.api.post(url('/rules'), {
    kind: 'keyword', keyword: keyword.value, site_id: keywordSite.value,
  }, silent)), () => { keyword.value = ''; keywordSite.value = null })
}
function addSite() {
  if (selectedSite.value == null || full.value) return
  return mutate(async () => unwrap(await props.api.post(url('/rules'), {
    kind: 'site', site_id: selectedSite.value,
  }, silent)), () => { selectedSite.value = null })
}
function deleteRule(rule: Rule) {
  return mutate(async () => unwrap(await props.api.delete(url(`/rules/${rule.id}`), silent)))
}
function blockHistory(item: HistoryItem) {
  if (!item.can_block || item.blocked || full.value) return
  return mutate(async () => unwrap(await props.api.post(url(`/history/${item.id}/block`), undefined, silent)))
}
function doSearch() {
  search.value = searchDraft.value
  historyPage.value = 1
  void loadHistory()
}
function changeRulePage(step: number) { rulePage.value += step; void loadRules() }
function changeHistoryPage(step: number) { historyPage.value += step; void loadHistory() }
function siteName(id: number | null | undefined) {
  return sites.value.find(site => site.id === id)?.name || `站点 ID ${id}`
}
watch(() => props.pluginId, () => {
  instance++
  ruleRequest++; historyRequest++; siteRequest++
  ruleList.value = []; history.value = []; sites.value = []
  totalRules.value = 0; totalHistory.value = 0
  rulePage.value = 1; historyPage.value = 1
  keyword.value = ''; keywordSite.value = null; selectedSite.value = null
  searchDraft.value = ''; search.value = ''; busy.value = false
  actionError.value = ''; notice.value = ''
  void loadRules(); void loadSites()
  if (tab.value === 'history') void loadHistory()
}, { immediate: true })
watch(tab, value => { if (value === 'history') void loadHistory() })
onBeforeUnmount(() => { instance++; ruleRequest++; historyRequest++; siteRequest++ })
</script>

<template>
  <section class="blacklist-page">
    <header>
      <h3>种子黑名单</h3>
      <p>规则永久保留，删除后恢复下载。请在插件配置中启用；停用时不拦截。</p>
    </header>
    <VAlert type="info" variant="tonal" :icon="false">
      关键词按标题和描述中的文字匹配，忽略大小写，不支持正则表达式。
      历史屏蔽仅匹配相同站点名称与完整种子标题；站点或种子改名后不再命中。
    </VAlert>
    <VAlert v-if="actionError" type="error" variant="tonal" :icon="false">{{ actionError }}</VAlert>
    <VAlert v-if="notice" type="success" variant="tonal" :icon="false">{{ notice }}</VAlert>
    <VAlert v-if="full" type="warning" variant="tonal" :icon="false">
      已达到 {{ capacity }} 条规则上限，请先删除不需要的规则。
    </VAlert>
    <VTabs v-model="tab" aria-label="黑名单管理">
      <VTab value="rules">规则</VTab>
      <VTab value="history">下载历史</VTab>
    </VTabs>

    <div v-if="tab === 'rules'" class="blacklist-panel">
      <VAlert v-if="sitesError" type="error" variant="tonal" :icon="false">
        站点列表加载失败：{{ sitesError }} <VBtn variant="text" @click="loadSites">重试站点</VBtn>
      </VAlert>
      <form class="blacklist-form" @submit.prevent="addKeyword">
        <VTextField v-model="keyword" label="关键词" maxlength="256" counter="256" :disabled="busy" />
        <VSelect v-model="keywordSite" label="限定站点（可选）" :menu-props="{ activatorProps: { 'aria-label': '限定站点（可选）' } }" :items="sites" item-title="name" item-value="id"
          clearable :disabled="busy" hint="留空匹配所有站点" persistent-hint />
        <VBtn type="submit" color="primary" :disabled="busy || full || !keyword.trim()">添加关键词</VBtn>
      </form>
      <form class="blacklist-site-form" @submit.prevent="addSite">
        <VSelect v-model="selectedSite" label="屏蔽站点" :menu-props="{ activatorProps: { 'aria-label': '屏蔽站点' } }" :items="sites" item-title="name" item-value="id"
          :disabled="busy" hide-details />
        <VBtn type="submit" variant="tonal" :disabled="busy || full || selectedSite == null">添加站点</VBtn>
      </form>
      <div class="blacklist-toolbar"><strong>已保存 {{ totalRules }} / {{ capacity }} 条规则</strong>
        <VBtn variant="text" :disabled="loadingRules" @click="loadRules">刷新规则</VBtn>
      </div>
      <VProgressLinear v-if="loadingRules" indeterminate aria-label="正在加载规则" />
      <VAlert v-if="ruleError" type="error" variant="tonal" :icon="false">{{ ruleError }}</VAlert>
      <p v-else-if="!loadingRules && !ruleList.length" class="blacklist-empty">暂无黑名单规则</p>
      <ul class="blacklist-list">
        <li v-for="rule in ruleList" :key="rule.id" class="blacklist-row">
          <div class="blacklist-facts">
            <template v-if="rule.kind === 'keyword'">
              <strong>关键词：{{ rule.keyword }}</strong>
              <span>{{ rule.site_id ? siteName(rule.site_id) : '所有站点' }}</span>
            </template>
            <template v-else-if="rule.kind === 'site'">
              <strong>{{ siteName(rule.site_id) }}</strong><span>屏蔽该站点所有种子 · ID {{ rule.site_id }}</span>
            </template>
            <template v-else>
              <strong>{{ rule.title }}</strong><span>{{ rule.site_name }} · 同站同名完整标题</span>
            </template>
          </div>
          <VBtn variant="text" color="error" :disabled="busy" aria-label="删除规则" @click="deleteRule(rule)">删除</VBtn>
        </li>
      </ul>
      <nav class="blacklist-pagination" aria-label="规则分页">
        <VBtn variant="text" :disabled="rulePage <= 1 || loadingRules" @click="changeRulePage(-1)">上一页规则</VBtn>
        <span>第 {{ rulePage }} 页</span>
        <VBtn variant="text" :disabled="rulePage * pageSize >= totalRules || loadingRules" @click="changeRulePage(1)">下一页规则</VBtn>
      </nav>
    </div>

    <div v-else class="blacklist-panel">
      <form class="blacklist-search" @submit.prevent="doSearch">
        <VTextField v-model="searchDraft" label="搜索媒体标题或下载路径" maxlength="256" hide-details />
        <VBtn type="submit" variant="tonal">搜索</VBtn>
      </form>
      <p>共 {{ totalHistory }} 条下载历史。屏蔽规则保存后，即使删除历史也会保留。</p>
      <VProgressLinear v-if="loadingHistory" indeterminate aria-label="正在加载历史" />
      <VAlert v-if="historyError" type="error" variant="tonal" :icon="false">
        {{ historyError }} <VBtn variant="text" @click="loadHistory">重试历史</VBtn>
      </VAlert>
      <p v-else-if="!loadingHistory && !history.length" class="blacklist-empty">暂无匹配的下载历史</p>
      <ul class="blacklist-list">
        <li v-for="item in history" :key="item.id" class="blacklist-row">
          <div class="blacklist-facts">
            <strong>{{ item.torrent_name || '缺少种子标题' }}</strong>
            <span>{{ item.title || '未知媒体' }} · {{ item.torrent_site || '缺少站点名称' }} · {{ item.date || '未知日期' }}</span>
            <span v-if="item.unavailable_reason">{{ item.unavailable_reason }}</span>
          </div>
          <VBtn variant="tonal" :disabled="busy || full || item.blocked || !item.can_block" @click="blockHistory(item)">
            {{ item.blocked ? '已添加' : !item.can_block ? '无法添加' : '屏蔽同站同名种子' }}
          </VBtn>
        </li>
      </ul>
      <nav class="blacklist-pagination" aria-label="历史分页">
        <VBtn variant="text" :disabled="historyPage <= 1 || loadingHistory" @click="changeHistoryPage(-1)">上一页历史</VBtn>
        <span>第 {{ historyPage }} 页</span>
        <VBtn variant="text" :disabled="historyPage * pageSize >= totalHistory || loadingHistory" @click="changeHistoryPage(1)">下一页历史</VBtn>
      </nav>
    </div>
  </section>
</template>

<style scoped>
.blacklist-page { display: grid; gap: 1rem; padding: 1rem; min-width: 0; }
.blacklist-page h3, .blacklist-page p { margin: 0; }
.blacklist-page header { display: grid; gap: .5rem; }
.blacklist-panel { display: grid; gap: 1rem; min-width: 0; }
.blacklist-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: .75rem; align-items: start; }
.blacklist-site-form, .blacklist-search { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .75rem; align-items: center; }
.blacklist-toolbar, .blacklist-pagination { display: flex; flex-wrap: wrap; gap: .5rem; justify-content: space-between; align-items: center; }
.blacklist-list { margin: 0; padding: 0; list-style: none; }
.blacklist-row { display: flex; align-items: center; gap: 1rem; padding: 1rem 0; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.blacklist-facts { display: grid; gap: .35rem; flex: 1; min-width: 0; overflow-wrap: anywhere; }
.blacklist-facts span { font-size: .875rem; opacity: .8; }
.blacklist-row > :last-child { flex-shrink: 0; }
.blacklist-empty { padding: 1rem 0; opacity: .75; }
@media (max-width: 600px) {
  .blacklist-form { grid-template-columns: minmax(0, 1fr); }
  .blacklist-row { align-items: flex-start; flex-direction: column; gap: .75rem; }
  .blacklist-row > :last-child { align-self: flex-end; }
  .blacklist-pagination { justify-content: center; }
}
</style>
