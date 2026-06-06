import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc, f as formatTokens, u as unwrapResponse } from './_plugin-vue_export-helper-B_eZRIX_.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createBlock:_createBlock,createElementVNode:_createElementVNode,unref:_unref,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-dashboard-widget" };
const _hoisted_2 = {
  key: 0,
  class: "agenttokens-dashboard-state"
};
const _hoisted_3 = {
  key: 2,
  class: "agenttokens-dashboard-content"
};
const _hoisted_4 = { class: "agenttokens-dashboard-summary" };
const _hoisted_5 = { class: "agenttokens-dashboard-summary__percent" };
const _hoisted_6 = { class: "agenttokens-dashboard-summary__body" };
const _hoisted_7 = { class: "agenttokens-dashboard-summary__count" };
const _hoisted_8 = { class: "agenttokens-dashboard-metrics" };
const _hoisted_9 = { class: "agenttokens-dashboard-metric" };
const _hoisted_10 = { class: "agenttokens-dashboard-metric" };
const _hoisted_11 = { class: "agenttokens-dashboard-metric" };
const _hoisted_12 = {
  key: 0,
  class: "agenttokens-dashboard-list"
};
const _hoisted_13 = { class: "agenttokens-dashboard-provider__main" };
const _hoisted_14 = { class: "agenttokens-dashboard-provider__name" };
const _hoisted_15 = { class: "agenttokens-dashboard-provider__model" };
const _hoisted_16 = { class: "agenttokens-dashboard-provider__tokens" };
const _hoisted_17 = {
  key: 1,
  class: "agenttokens-dashboard-empty"
};
const _hoisted_18 = {
  key: 3,
  class: "agenttokens-dashboard-state text-caption text-disabled"
};
const _hoisted_19 = { class: "text-caption text-disabled" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  config: {
    type: Object,
    default: () => ({ attrs: {} }),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
  refreshInterval: {
    type: Number,
    default: 0,
  },
},
  setup(__props) {

const props = __props;

const loading = ref(false);
const error = ref('');
const initialDataLoaded = ref(false);
const lastRefreshedAt = ref(null);
const status = ref({ providers: [], summary: {} });
let timer = null;

const attrs = computed(() => props.config?.attrs || {});
const summary = computed(() => status.value.summary || {});
const providers = computed(() => status.value.providers || []);
const visibleProviders = computed(() => providers.value.slice(0, 3));
const totalUsed = computed(() => Number(summary.value.total_used || 0));
const totalLimit = computed(() => Number(summary.value.total_limit || 0));
const remainingTokens = computed(() => {
  if (totalLimit.value <= 0) return null
  return Math.max(totalLimit.value - totalUsed.value, 0)
});
const usagePercent = computed(() => {
  if (totalLimit.value <= 0) return 0
  return Math.min((totalUsed.value * 100) / totalLimit.value, 100)
});
const usagePercentText = computed(() => (totalLimit.value > 0 ? `${Math.round(usagePercent.value)}%` : '不限'));
const progressColor = computed(() => {
  if (totalLimit.value <= 0) return 'primary'
  if (usagePercent.value >= 90) return 'error'
  if (usagePercent.value >= 70) return 'warning'
  return 'success'
});
// 兼容宿主传入的数字或字符串刷新间隔。
const refreshSeconds = computed(() => {
  const seconds = Number(props.refreshInterval || attrs.value.refresh || 0);
  return Number.isFinite(seconds) ? seconds : 0
});
const cardTitle = computed(() => attrs.value.title || 'Agent Tokens 管理');
const cardSubtitle = computed(() => attrs.value.subtitle || 'LLM 配额使用情况');
const cardFlat = computed(() => attrs.value.border === false);
const lastRefreshedTime = computed(() => {
  if (!lastRefreshedAt.value) return ''
  return new Date(lastRefreshedAt.value).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })
});

// 读取 Agent Tokens 仪表板状态。
async function loadStatus() {
  if (!props.api?.get) {
    error.value = 'API 未就绪';
    return
  }
  loading.value = true;
  error.value = '';
  try {
    const response = await props.api.get('plugin/AgentTokens/status');
    status.value = unwrapResponse(response) || status.value;
    initialDataLoaded.value = true;
    lastRefreshedAt.value = Date.now();
  } catch (err) {
    error.value = err?.message || '获取数据失败';
  } finally {
    loading.value = false;
  }
}

// 启动宿主传入或插件配置中的自动刷新。
function startRefreshTimer() {
  if (refreshSeconds.value <= 0) return
  timer = window.setInterval(loadStatus, refreshSeconds.value * 1000);
}

// 清理仪表板自动刷新计时器。
function stopRefreshTimer() {
  if (!timer) return
  window.clearInterval(timer);
  timer = null;
}

onMounted(() => {
  loadStatus();
  startRefreshTimer();
});

onUnmounted(() => {
  stopRefreshTimer();
});

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VAvatar = _resolveComponent("VAvatar");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardSubtitle = _resolveComponent("VCardSubtitle");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VProgressCircular = _resolveComponent("VProgressCircular");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VCard, {
      flat: cardFlat.value,
      loading: loading.value,
      class: "agenttokens-dashboard-card"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardItem, { class: "agenttokens-dashboard-card__header" }, {
          prepend: _withCtx(() => [
            _createVNode(_component_VAvatar, {
              color: "primary",
              variant: "tonal",
              size: "36"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-key-chain",
                  size: "20"
                })
              ]),
              _: 1
            })
          ]),
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "agenttokens-dashboard-card__title" }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(cardTitle.value), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VCardSubtitle, null, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(cardSubtitle.value), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VCardText, { class: "agenttokens-dashboard-card__body" }, {
          default: _withCtx(() => [
            (loading.value && !initialDataLoaded.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_2, [
                  _createVNode(_component_VProgressCircular, {
                    indeterminate: "",
                    color: "primary",
                    size: "28"
                  })
                ]))
              : (error.value)
                ? (_openBlock(), _createBlock(_component_VAlert, {
                    key: 1,
                    type: "error",
                    variant: "tonal",
                    density: "compact",
                    class: "text-caption"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(error.value), 1)
                    ]),
                    _: 1
                  }))
                : (initialDataLoaded.value)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
                      _createElementVNode("div", _hoisted_4, [
                        _createVNode(_component_VProgressCircular, {
                          "model-value": usagePercent.value,
                          color: progressColor.value,
                          "bg-color": "surface-variant",
                          size: 84,
                          width: 8
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("span", _hoisted_5, _toDisplayString(usagePercentText.value), 1)
                          ]),
                          _: 1
                        }, 8, ["model-value", "color"]),
                        _createElementVNode("div", _hoisted_6, [
                          _cache[0] || (_cache[0] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "可用供应商", -1)),
                          _createElementVNode("div", _hoisted_7, [
                            _createTextVNode(_toDisplayString(summary.value.available_count || 0) + " ", 1),
                            _createElementVNode("span", null, "/ " + _toDisplayString(summary.value.enabled_count || 0), 1)
                          ]),
                          _createVNode(_component_VProgressLinear, {
                            "model-value": usagePercent.value,
                            color: progressColor.value,
                            height: "6",
                            rounded: ""
                          }, null, 8, ["model-value", "color"])
                        ])
                      ]),
                      _createElementVNode("div", _hoisted_8, [
                        _createElementVNode("div", _hoisted_9, [
                          _cache[1] || (_cache[1] = _createElementVNode("span", null, "累计", -1)),
                          _createElementVNode("strong", null, _toDisplayString(_unref(formatTokens)(totalUsed.value)), 1)
                        ]),
                        _createElementVNode("div", _hoisted_10, [
                          _cache[2] || (_cache[2] = _createElementVNode("span", null, "额度", -1)),
                          _createElementVNode("strong", null, _toDisplayString(totalLimit.value > 0 ? _unref(formatTokens)(totalLimit.value) : '不限'), 1)
                        ]),
                        _createElementVNode("div", _hoisted_11, [
                          _cache[3] || (_cache[3] = _createElementVNode("span", null, "剩余", -1)),
                          _createElementVNode("strong", null, _toDisplayString(remainingTokens.value === null ? '不限' : _unref(formatTokens)(remainingTokens.value)), 1)
                        ])
                      ]),
                      (visibleProviders.value.length)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_12, [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(visibleProviders.value, (row) => {
                              return (_openBlock(), _createElementBlock("div", {
                                key: row.id,
                                class: "agenttokens-dashboard-provider"
                              }, [
                                _createVNode(_component_VIcon, {
                                  icon: row.usage?.exhausted ? 'mdi-alert-circle' : 'mdi-check-circle',
                                  color: row.usage?.exhausted ? 'error' : 'success',
                                  size: "16"
                                }, null, 8, ["icon", "color"]),
                                _createElementVNode("div", _hoisted_13, [
                                  _createElementVNode("div", _hoisted_14, _toDisplayString(row.name || '未命名供应商'), 1),
                                  _createElementVNode("div", _hoisted_15, _toDisplayString(row.model || '未配置模型'), 1)
                                ]),
                                _createElementVNode("div", _hoisted_16, _toDisplayString(_unref(formatTokens)(row.usage?.total_tokens)), 1)
                              ]))
                            }), 128))
                          ]))
                        : (_openBlock(), _createElementBlock("div", _hoisted_17, [
                            _createVNode(_component_VIcon, {
                              icon: "mdi-database-off-outline",
                              size: "18"
                            }),
                            _cache[4] || (_cache[4] = _createElementVNode("span", null, "暂无供应商", -1))
                          ]))
                    ]))
                  : (_openBlock(), _createElementBlock("div", _hoisted_18, " 暂无数据 "))
          ]),
          _: 1
        }),
        (__props.allowRefresh)
          ? (_openBlock(), _createBlock(_component_VDivider, { key: 0 }))
          : _createCommentVNode("", true),
        (__props.allowRefresh)
          ? (_openBlock(), _createBlock(_component_VCardActions, {
              key: 1,
              class: "agenttokens-dashboard-card__actions"
            }, {
              default: _withCtx(() => [
                _createElementVNode("span", _hoisted_19, _toDisplayString(lastRefreshedTime.value ? `更新于 ${lastRefreshedTime.value}` : '等待更新'), 1),
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  icon: "",
                  variant: "text",
                  size: "small",
                  loading: loading.value,
                  onClick: loadStatus
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-refresh",
                      size: "18"
                    })
                  ]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _: 1
            }))
          : _createCommentVNode("", true)
      ]),
      _: 1
    }, 8, ["flat", "loading"])
  ]))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-7844b861"]]);

export { Dashboard as default };
