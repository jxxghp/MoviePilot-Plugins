import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-page pa-4" };
const _hoisted_2 = { class: "d-flex align-center gap-2 mb-4 flex-wrap" };
const _hoisted_3 = { class: "text-h5" };
const _hoisted_4 = { class: "text-h5" };
const _hoisted_5 = { class: "text-h5" };
const _hoisted_6 = { class: "d-flex flex-column" };
const _hoisted_7 = { class: "progress-cell" };
const _hoisted_8 = { class: "text-right" };
const _hoisted_9 = { key: 0 };
const _hoisted_10 = { class: "d-flex justify-end mb-3 gap-2" };
const _hoisted_11 = { class: "truncate-cell" };
const _hoisted_12 = { class: "text-right" };
const _hoisted_13 = { key: 0 };

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
  navKey: {
    type: String,
    default: 'main',
  },
},
  setup(__props) {

const props = __props;

const loading = ref(false);
const saving = ref(false);
const error = ref('');
const activeTab = ref('usage');
const showEditor = ref(false);
const editorIndex = ref(-1);
const editedProvider = ref(createProvider());
const status = ref({
  config: { enabled: false, providers: [] },
  providers: [],
  summary: {},
});

const pluginBase = computed(() => `plugin/${props.pluginId || 'AgentTokens'}`);
const config = computed(() => status.value.config || { enabled: false, providers: [] });
const providerRows = computed(() => status.value.providers || []);
const summary = computed(() => status.value.summary || {});

const providerTypeOptions = [
  { title: 'OpenAI Compatible', value: 'openai' },
  { title: 'DeepSeek', value: 'deepseek' },
  { title: 'Google Gemini', value: 'google' },
  { title: 'Anthropic Compatible', value: 'anthropic' },
  { title: 'ChatGPT', value: 'chatgpt' },
];

// 构建一个新的供应商默认配置。
function createProvider() {
  return {
    id: '',
    enabled: true,
    name: '',
    provider: 'openai',
    base_url: '',
    api_key: '',
    model: '',
    token_limit: 0,
    used_tokens: 0,
    priority: 1,
  }
}

// 兼容 MoviePilot API 包装器和原始响应两种返回形态。
function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

// 格式化 token 数字，保持表格紧凑可读。
function formatTokens(value) {
  const numberValue = Number(value || 0);
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : '0'
}

// 根据供应商状态返回 Vuetify 颜色。
function rowStatusColor(row) {
  if (!row.enabled) return 'default'
  if (row.usage?.exhausted) return 'error'
  if (!row.api_key || !row.base_url || !row.model) return 'warning'
  return 'success'
}

// 根据供应商状态返回短标签。
function rowStatusText(row) {
  if (!row.enabled) return '停用'
  if (row.usage?.exhausted) return '耗尽'
  if (!row.api_key || !row.base_url || !row.model) return '缺配置'
  return '可用'
}

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

// 打开新增供应商弹窗。
function addProvider() {
  const nextPriority = Math.max(0, ...(config.value.providers || []).map(item => Number(item.priority || 0))) + 1;
  editedProvider.value = { ...createProvider(), priority: nextPriority };
  editorIndex.value = -1;
  showEditor.value = true;
}

// 打开编辑供应商弹窗。
function editProvider(index) {
  editedProvider.value = { ...config.value.providers[index] };
  editorIndex.value = index;
  showEditor.value = true;
}

// 将弹窗中的供应商写回配置列表。
function commitProvider() {
  const providers = [...(config.value.providers || [])];
  const normalized = {
    ...editedProvider.value,
    token_limit: Number(editedProvider.value.token_limit || 0),
    used_tokens: Number(editedProvider.value.used_tokens || 0),
    priority: Number(editedProvider.value.priority || providers.length + 1),
  };
  if (editorIndex.value >= 0) {
    providers.splice(editorIndex.value, 1, normalized);
  } else {
    providers.push(normalized);
  }
  status.value.config = { ...config.value, providers };
  showEditor.value = false;
}

// 从配置列表中移除一个供应商。
function removeProvider(index) {
  const providers = [...(config.value.providers || [])];
  providers.splice(index, 1);
  status.value.config = { ...config.value, providers };
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

onMounted(loadStatus);

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSheet = _resolveComponent("VSheet");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VTab = _resolveComponent("VTab");
  const _component_VTabs = _resolveComponent("VTabs");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VTable = _resolveComponent("VTable");
  const _component_VWindowItem = _resolveComponent("VWindowItem");
  const _component_VWindow = _resolveComponent("VWindow");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[15] || (_cache[15] = _createElementVNode("div", { class: "text-h5 font-weight-medium" }, "Agent Tokens 管理", -1)),
      _createVNode(_component_VSpacer),
      _createVNode(_component_VBtn, {
        icon: "mdi-refresh",
        variant: "text",
        loading: loading.value,
        onClick: loadStatus
      }, null, 8, ["loading"]),
      _createVNode(_component_VBtn, {
        "prepend-icon": "mdi-content-save",
        color: "primary",
        loading: saving.value,
        onClick: saveConfig
      }, {
        default: _withCtx(() => _cache[14] || (_cache[14] = [
          _createTextVNode("保存")
        ])),
        _: 1
      }, 8, ["loading"])
    ]),
    (error.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_VRow, { class: "mb-2" }, {
      default: _withCtx(() => [
        _createVNode(_component_VCol, {
          cols: "12",
          sm: "6",
          md: "3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSheet, {
              border: "",
              rounded: "",
              class: "pa-4 h-100"
            }, {
              default: _withCtx(() => [
                _cache[16] || (_cache[16] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "可用供应商", -1)),
                _createElementVNode("div", _hoisted_3, _toDisplayString(summary.value.available_count || 0) + " / " + _toDisplayString(summary.value.enabled_count || 0), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          sm: "6",
          md: "3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSheet, {
              border: "",
              rounded: "",
              class: "pa-4 h-100"
            }, {
              default: _withCtx(() => [
                _cache[17] || (_cache[17] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "累计使用", -1)),
                _createElementVNode("div", _hoisted_4, _toDisplayString(formatTokens(summary.value.total_used)), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          sm: "6",
          md: "3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSheet, {
              border: "",
              rounded: "",
              class: "pa-4 h-100"
            }, {
              default: _withCtx(() => [
                _cache[18] || (_cache[18] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "总额度", -1)),
                _createElementVNode("div", _hoisted_5, _toDisplayString(formatTokens(summary.value.total_limit)), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VCol, {
          cols: "12",
          sm: "6",
          md: "3"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VSheet, {
              border: "",
              rounded: "",
              class: "pa-4 h-100 d-flex align-center"
            }, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_6, [
                  _createVNode(_component_VSwitch, {
                    modelValue: status.value.config.enabled,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((status.value.config.enabled) = $event)),
                    color: "primary",
                    "hide-details": "",
                    inset: "",
                    label: "启用插件"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_VSwitch, {
                    modelValue: status.value.config.show_sidebar_nav,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((status.value.config.show_sidebar_nav) = $event)),
                    color: "primary",
                    "hide-details": "",
                    inset: "",
                    density: "compact",
                    label: "侧边栏入口"
                  }, null, 8, ["modelValue"])
                ])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VTabs, {
      modelValue: activeTab.value,
      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((activeTab).value = $event)),
      density: "comfortable",
      class: "mb-3"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VTab, { value: "usage" }, {
          default: _withCtx(() => _cache[19] || (_cache[19] = [
            _createTextVNode("用量")
          ])),
          _: 1
        }),
        _createVNode(_component_VTab, { value: "config" }, {
          default: _withCtx(() => _cache[20] || (_cache[20] = [
            _createTextVNode("配置")
          ])),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VWindow, {
      modelValue: activeTab.value,
      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((activeTab).value = $event))
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VWindowItem, { value: "usage" }, {
          default: _withCtx(() => [
            _createVNode(_component_VSheet, {
              border: "",
              rounded: ""
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTable, { density: "comfortable" }, {
                  default: _withCtx(() => [
                    _cache[22] || (_cache[22] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", null, "优先级"),
                        _createElementVNode("th", null, "名称"),
                        _createElementVNode("th", null, "模型"),
                        _createElementVNode("th", null, "已用"),
                        _createElementVNode("th", null, "余量"),
                        _createElementVNode("th", null, "进度"),
                        _createElementVNode("th", null, "状态"),
                        _createElementVNode("th", { class: "text-right" }, "操作")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(providerRows.value, (row) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: row.id
                        }, [
                          _createElementVNode("td", null, _toDisplayString(row.priority), 1),
                          _createElementVNode("td", null, _toDisplayString(row.name), 1),
                          _createElementVNode("td", null, _toDisplayString(row.model), 1),
                          _createElementVNode("td", null, _toDisplayString(formatTokens(row.usage?.total_tokens)), 1),
                          _createElementVNode("td", null, _toDisplayString(row.usage?.remaining_tokens === null ? '不限' : formatTokens(row.usage?.remaining_tokens)), 1),
                          _createElementVNode("td", _hoisted_7, [
                            _createVNode(_component_VProgressLinear, {
                              "model-value": row.usage?.usage_percent || 0,
                              color: rowStatusColor(row),
                              height: "8",
                              rounded: ""
                            }, null, 8, ["model-value", "color"])
                          ]),
                          _createElementVNode("td", null, [
                            _createVNode(_component_VChip, {
                              size: "small",
                              color: rowStatusColor(row),
                              variant: "tonal"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(rowStatusText(row)), 1)
                              ]),
                              _: 2
                            }, 1032, ["color"])
                          ]),
                          _createElementVNode("td", _hoisted_8, [
                            _createVNode(_component_VBtn, {
                              icon: "mdi-backup-restore",
                              size: "small",
                              variant: "text",
                              onClick: $event => (resetUsage(row.id))
                            }, null, 8, ["onClick"])
                          ])
                        ]))
                      }), 128)),
                      (!providerRows.value.length)
                        ? (_openBlock(), _createElementBlock("tr", _hoisted_9, _cache[21] || (_cache[21] = [
                            _createElementVNode("td", {
                              colspan: "8",
                              class: "text-center text-medium-emphasis py-8"
                            }, "暂无供应商", -1)
                          ])))
                        : _createCommentVNode("", true)
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VWindowItem, { value: "config" }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_10, [
              _createVNode(_component_VBtn, {
                "prepend-icon": "mdi-plus",
                color: "primary",
                variant: "tonal",
                onClick: addProvider
              }, {
                default: _withCtx(() => _cache[23] || (_cache[23] = [
                  _createTextVNode("新增")
                ])),
                _: 1
              }),
              _createVNode(_component_VBtn, {
                "prepend-icon": "mdi-backup-restore",
                color: "warning",
                variant: "tonal",
                onClick: resetAllUsage
              }, {
                default: _withCtx(() => _cache[24] || (_cache[24] = [
                  _createTextVNode("重置用量")
                ])),
                _: 1
              })
            ]),
            _createVNode(_component_VSheet, {
              border: "",
              rounded: ""
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VTable, { density: "comfortable" }, {
                  default: _withCtx(() => [
                    _cache[26] || (_cache[26] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", null, "启用"),
                        _createElementVNode("th", null, "优先级"),
                        _createElementVNode("th", null, "名称"),
                        _createElementVNode("th", null, "类型"),
                        _createElementVNode("th", null, "地址"),
                        _createElementVNode("th", null, "Key"),
                        _createElementVNode("th", null, "模型"),
                        _createElementVNode("th", null, "额度"),
                        _createElementVNode("th", { class: "text-right" }, "操作")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.value.providers, (row, index) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: row.id || index
                        }, [
                          _createElementVNode("td", null, [
                            _createVNode(_component_VSwitch, {
                              modelValue: row.enabled,
                              "onUpdate:modelValue": $event => ((row.enabled) = $event),
                              color: "primary",
                              "hide-details": "",
                              density: "compact"
                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                          ]),
                          _createElementVNode("td", null, _toDisplayString(row.priority), 1),
                          _createElementVNode("td", null, _toDisplayString(row.name), 1),
                          _createElementVNode("td", null, _toDisplayString(row.provider), 1),
                          _createElementVNode("td", _hoisted_11, _toDisplayString(row.base_url), 1),
                          _createElementVNode("td", null, _toDisplayString(providerRows.value[index]?.masked_api_key || '****'), 1),
                          _createElementVNode("td", null, _toDisplayString(row.model), 1),
                          _createElementVNode("td", null, _toDisplayString(row.token_limit > 0 ? formatTokens(row.token_limit) : '不限'), 1),
                          _createElementVNode("td", _hoisted_12, [
                            _createVNode(_component_VBtn, {
                              icon: "mdi-pencil",
                              size: "small",
                              variant: "text",
                              onClick: $event => (editProvider(index))
                            }, null, 8, ["onClick"]),
                            _createVNode(_component_VBtn, {
                              icon: "mdi-delete",
                              size: "small",
                              variant: "text",
                              color: "error",
                              onClick: $event => (removeProvider(index))
                            }, null, 8, ["onClick"])
                          ])
                        ]))
                      }), 128)),
                      (!config.value.providers?.length)
                        ? (_openBlock(), _createElementBlock("tr", _hoisted_13, _cache[25] || (_cache[25] = [
                            _createElementVNode("td", {
                              colspan: "9",
                              class: "text-center text-medium-emphasis py-8"
                            }, "暂无供应商", -1)
                          ])))
                        : _createCommentVNode("", true)
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VDialog, {
      modelValue: showEditor.value,
      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((showEditor).value = $event)),
      "max-width": "760"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, null, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(editorIndex.value >= 0 ? '编辑供应商' : '新增供应商'), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "8"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.name,
                          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((editedProvider.value.name) = $event)),
                          label: "名称",
                          variant: "outlined",
                          density: "comfortable"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.priority,
                          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((editedProvider.value.priority) = $event)),
                          modelModifiers: { number: true },
                          label: "优先级",
                          type: "number",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSelect, {
                          modelValue: editedProvider.value.provider,
                          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((editedProvider.value.provider) = $event)),
                          items: providerTypeOptions,
                          label: "类型",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.model,
                          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((editedProvider.value.model) = $event)),
                          label: "模型",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.base_url,
                          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((editedProvider.value.base_url) = $event)),
                          label: "API 地址",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.api_key,
                          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((editedProvider.value.api_key) = $event)),
                          label: "API Key",
                          type: "password",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.token_limit,
                          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((editedProvider.value.token_limit) = $event)),
                          modelModifiers: { number: true },
                          label: "Token 额度",
                          type: "number",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.used_tokens,
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((editedProvider.value.used_tokens) = $event)),
                          modelModifiers: { number: true },
                          label: "初始已用",
                          type: "number",
                          variant: "outlined"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardActions, null, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[12] || (_cache[12] = $event => (showEditor.value = false))
                }, {
                  default: _withCtx(() => _cache[27] || (_cache[27] = [
                    _createTextVNode("取消")
                  ])),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  onClick: commitProvider
                }, {
                  default: _withCtx(() => _cache[28] || (_cache[28] = [
                    _createTextVNode("确定")
                  ])),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-732593d9"]]);

export { AppPage as default };
