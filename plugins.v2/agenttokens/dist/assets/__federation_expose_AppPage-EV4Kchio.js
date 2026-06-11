import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { A as AgentTokensManager } from './AgentTokensManager-BTcJgtTd.js';
import { u as unwrapResponse } from './_plugin-vue_export-helper-B_eZRIX_.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const {computed,onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'AgentTokens',
  },
  hideTitle: {
    type: Boolean,
    default: false,
  },
},
  setup(__props, { expose: __expose }) {

const props = __props;

const loading = ref(false);
const saving = ref(false);
const error = ref('');
const status = ref({
  config: { enabled: false, show_sidebar_nav: true, providers: [] },
  providers: [],
  summary: {},
});

// 构造 API 基础路径。
const pluginBase = computed(() => `plugin/${props.pluginId || 'AgentTokens'}`);
const config = computed(() => status.value.config || { enabled: false, show_sidebar_nav: true, providers: [] });
const providerRows = computed(() => status.value.providers || []);
const summary = computed(() => status.value.summary || {});

// 从插件 API 拉取当前配置和用量状态。
async function loadStatus() {
  loading.value = true;
  error.value = '';
  try {
    const response = await props.api.get(`${pluginBase.value}/status`);
    status.value = unwrapResponse(response) || status.value;
  } catch (err) {
    error.value = err?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

// 保存完整插件配置并刷新服务端标准化后的状态。
async function saveConfig() {
  saving.value = true;
  error.value = '';
  try {
    const payload = {
      enabled: Boolean(config.value.enabled),
      show_sidebar_nav: Boolean(config.value.show_sidebar_nav),
      providers: [...(config.value.providers || [])],
    };
    const response = await props.api.post(`${pluginBase.value}/config`, payload);
    status.value = unwrapResponse(response) || status.value;
  } catch (err) {
    error.value = err?.message || '保存失败';
  } finally {
    saving.value = false;
  }
}

// 重置指定供应商的运行记录。
async function resetUsage(providerId) {
  if (!providerId) return
  loading.value = true;
  try {
    const response = await props.api.post(`${pluginBase.value}/usage/reset`, { provider_id: providerId });
    status.value = unwrapResponse(response) || status.value;
  } finally {
    loading.value = false;
  }
}

// 重置全部供应商的运行记录。
async function resetAllUsage() {
  loading.value = true;
  try {
    const response = await props.api.post(`${pluginBase.value}/usage/reset_all`, {});
    status.value = unwrapResponse(response) || status.value;
  } finally {
    loading.value = false;
  }
}

__expose({
  loadStatus,
  saveConfig,
  loading,
  saving,
});

onMounted(loadStatus);

return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(AgentTokensManager, {
    config: config.value,
    "provider-rows": providerRows.value,
    summary: summary.value,
    error: error.value,
    loading: loading.value,
    saving: saving.value,
    "hide-title": __props.hideTitle,
    onRefresh: loadStatus,
    onSave: saveConfig,
    onResetUsage: resetUsage,
    onResetAllUsage: resetAllUsage
  }, null, 8, ["config", "provider-rows", "summary", "error", "loading", "saving", "hide-title"]))
}
}

};

export { _sfc_main as default };
