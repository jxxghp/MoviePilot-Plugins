import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,createCommentVNode:_createCommentVNode} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-config" };
const _hoisted_2 = { class: "pa-4" };
const _hoisted_3 = { class: "d-flex align-center mb-4 gap-2 flex-wrap" };
const _hoisted_4 = { class: "text-right" };
const _hoisted_5 = { key: 0 };
const _hoisted_6 = { class: "pa-4 d-flex justify-end" };

const {onMounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const localConfig = ref({ enabled: false, show_sidebar_nav: true, providers: [] });
const showEditor = ref(false);
const editorIndex = ref(-1);
const editedProvider = ref(createProvider());

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
    user_agent: '',
    model: '',
    token_limit: 0,
    used_tokens: 0,
    priority: 1,
  }
}

// 生成深拷贝配置，避免直接修改父组件传入对象。
function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config || { enabled: false, show_sidebar_nav: true, providers: [] }))
}

// 格式化 token 数字。
function formatTokens(value) {
  const numberValue = Number(value || 0);
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : '0'
}

// 打开新增供应商弹窗。
function addProvider() {
  const nextPriority = Math.max(0, ...(localConfig.value.providers || []).map(item => Number(item.priority || 0))) + 1;
  editedProvider.value = { ...createProvider(), priority: nextPriority };
  editorIndex.value = -1;
  showEditor.value = true;
}

// 打开编辑供应商弹窗。
function editProvider(index) {
  editedProvider.value = { ...localConfig.value.providers[index] };
  editorIndex.value = index;
  showEditor.value = true;
}

// 将弹窗中的供应商写回本地配置。
function commitProvider() {
  const providers = [...(localConfig.value.providers || [])];
  const provider = {
    ...editedProvider.value,
    token_limit: Number(editedProvider.value.token_limit || 0),
    used_tokens: Number(editedProvider.value.used_tokens || 0),
    priority: Number(editedProvider.value.priority || providers.length + 1),
  };
  if (editorIndex.value >= 0) {
    providers.splice(editorIndex.value, 1, provider);
  } else {
    providers.push(provider);
  }
  localConfig.value.providers = providers;
  showEditor.value = false;
}

// 移除一个供应商配置。
function removeProvider(index) {
  const providers = [...(localConfig.value.providers || [])];
  providers.splice(index, 1);
  localConfig.value.providers = providers;
}

// 通知宿主保存 Vue 配置。
function saveConfig() {
  emit('save', cloneConfig(localConfig.value));
}

onMounted(() => {
  localConfig.value = cloneConfig(props.initialConfig);
  if (localConfig.value.show_sidebar_nav === undefined) {
    localConfig.value.show_sidebar_nav = true;
  }
  if (!Array.isArray(localConfig.value.providers)) {
    localConfig.value.providers = [];
  }
});

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VTable = _resolveComponent("VTable");
  const _component_VSheet = _resolveComponent("VSheet");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      color: "transparent"
    }, {
      default: _withCtx(() => [
        _cache[15] || (_cache[15] = _createElementVNode("div", { class: "text-h6 ms-3" }, "Agent Tokens 配置", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.enabled,
          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localConfig.value.enabled) = $event)),
          color: "primary",
          "hide-details": "",
          inset: "",
          label: "启用插件"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSwitch, {
          modelValue: localConfig.value.show_sidebar_nav,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((localConfig.value.show_sidebar_nav) = $event)),
          color: "primary",
          "hide-details": "",
          inset: "",
          label: "显示侧边栏入口"
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          "prepend-icon": "mdi-database-eye",
          variant: "tonal",
          onClick: _cache[3] || (_cache[3] = $event => (emit('switch')))
        }, {
          default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
            _createTextVNode("用量", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VBtn, {
          "prepend-icon": "mdi-plus",
          color: "primary",
          variant: "tonal",
          onClick: addProvider
        }, {
          default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
            _createTextVNode("新增", -1)
          ]))]),
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
              _cache[19] || (_cache[19] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", null, "启用"),
                  _createElementVNode("th", null, "优先级"),
                  _createElementVNode("th", null, "名称"),
                  _createElementVNode("th", null, "类型"),
                  _createElementVNode("th", null, "模型"),
                  _createElementVNode("th", null, "额度"),
                  _createElementVNode("th", { class: "text-right" }, "操作")
                ])
              ], -1)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(localConfig.value.providers, (row, index) => {
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
                    _createElementVNode("td", null, _toDisplayString(row.model), 1),
                    _createElementVNode("td", null, _toDisplayString(row.token_limit > 0 ? formatTokens(row.token_limit) : '不限'), 1),
                    _createElementVNode("td", _hoisted_4, [
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
                (!localConfig.value.providers.length)
                  ? (_openBlock(), _createElementBlock("tr", _hoisted_5, [...(_cache[18] || (_cache[18] = [
                      _createElementVNode("td", {
                        colspan: "7",
                        class: "text-center text-medium-emphasis py-8"
                      }, "暂无供应商", -1)
                    ]))]))
                  : _createCommentVNode("", true)
              ])
            ]),
            _: 1
          })
        ]),
        _: 1
      })
    ]),
    _createVNode(_component_VDivider),
    _createElementVNode("div", _hoisted_6, [
      _createVNode(_component_VBtn, {
        "prepend-icon": "mdi-content-save",
        color: "primary",
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
          _createTextVNode("保存", -1)
        ]))]),
        _: 1
      })
    ]),
    _createVNode(_component_VDialog, {
      modelValue: showEditor.value,
      "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((showEditor).value = $event)),
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
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: editedProvider.value.user_agent,
                          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((editedProvider.value.user_agent) = $event)),
                          label: "User-Agent",
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
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((editedProvider.value.token_limit) = $event)),
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
                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((editedProvider.value.used_tokens) = $event)),
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
                  onClick: _cache[13] || (_cache[13] = $event => (showEditor.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  onClick: commitProvider
                }, {
                  default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                    _createTextVNode("确定", -1)
                  ]))]),
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-ad13eb37"]]);

export { Config as default };
