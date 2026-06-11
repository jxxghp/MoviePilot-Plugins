import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc, f as formatTokens, P as PROVIDER_TYPE_OPTIONS, d as createProvider, b as buildProviderRows, a as buildProviderSummary, g as getNextProviderPriority, n as normalizeProvider } from './_plugin-vue_export-helper-B_eZRIX_.js';

const {createElementVNode:_createElementVNode$3,openBlock:_openBlock$4,createElementBlock:_createElementBlock$2,createCommentVNode:_createCommentVNode$2,renderList:_renderList$1,Fragment:_Fragment$1,resolveComponent:_resolveComponent$4,createVNode:_createVNode$4,toDisplayString:_toDisplayString$4,createTextVNode:_createTextVNode$4,withCtx:_withCtx$4,unref:_unref$4,createBlock:_createBlock$4} = await importShared('vue');


const _hoisted_1$3 = { key: 0 };
const _hoisted_2$3 = { key: 1 };
const _hoisted_3$3 = {
  key: 0,
  class: "truncate-cell"
};
const _hoisted_4$2 = { key: 1 };
const _hoisted_5$2 = { class: "text-right" };
const _hoisted_6$2 = { key: 0 };
const _hoisted_7$2 = ["colspan"];


const _sfc_main$4 = {
  __name: 'ProviderConfigTable',
  props: {
  providers: {
    type: Array,
    default: () => [],
  },
  providerRows: {
    type: Array,
    default: () => [],
  },
  showCredentials: {
    type: Boolean,
    default: false,
  },
},
  emits: ['edit', 'remove'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

// 获取管理页服务端返回的脱敏 Key。
function getMaskedApiKey(index) {
  return props.providerRows[index]?.masked_api_key || '****'
}

return (_ctx, _cache) => {
  const _component_VSwitch = _resolveComponent$4("VSwitch");
  const _component_VChip = _resolveComponent$4("VChip");
  const _component_VBtn = _resolveComponent$4("VBtn");
  const _component_VTable = _resolveComponent$4("VTable");
  const _component_VSheet = _resolveComponent$4("VSheet");

  return (_openBlock$4(), _createBlock$4(_component_VSheet, {
    border: "",
    rounded: "",
    class: "provider-table-shell"
  }, {
    default: _withCtx$4(() => [
      _createVNode$4(_component_VTable, { density: "comfortable" }, {
        default: _withCtx$4(() => [
          _createElementVNode$3("thead", null, [
            _createElementVNode$3("tr", null, [
              _cache[0] || (_cache[0] = _createElementVNode$3("th", null, "启用", -1)),
              _cache[1] || (_cache[1] = _createElementVNode$3("th", null, "优先级", -1)),
              _cache[2] || (_cache[2] = _createElementVNode$3("th", null, "名称", -1)),
              _cache[3] || (_cache[3] = _createElementVNode$3("th", null, "类型", -1)),
              (__props.showCredentials)
                ? (_openBlock$4(), _createElementBlock$2("th", _hoisted_1$3, "地址"))
                : _createCommentVNode$2("", true),
              (__props.showCredentials)
                ? (_openBlock$4(), _createElementBlock$2("th", _hoisted_2$3, "Key"))
                : _createCommentVNode$2("", true),
              _cache[4] || (_cache[4] = _createElementVNode$3("th", null, "代理", -1)),
              _cache[5] || (_cache[5] = _createElementVNode$3("th", null, "模型", -1)),
              _cache[6] || (_cache[6] = _createElementVNode$3("th", null, "额度", -1)),
              _cache[7] || (_cache[7] = _createElementVNode$3("th", { class: "text-right" }, "操作", -1))
            ])
          ]),
          _createElementVNode$3("tbody", null, [
            (_openBlock$4(true), _createElementBlock$2(_Fragment$1, null, _renderList$1(__props.providers, (row, index) => {
              return (_openBlock$4(), _createElementBlock$2("tr", {
                key: row.id || index
              }, [
                _createElementVNode$3("td", null, [
                  _createVNode$4(_component_VSwitch, {
                    modelValue: row.enabled,
                    "onUpdate:modelValue": $event => ((row.enabled) = $event),
                    color: "primary",
                    "hide-details": "",
                    density: "compact"
                  }, null, 8, ["modelValue", "onUpdate:modelValue"])
                ]),
                _createElementVNode$3("td", null, _toDisplayString$4(row.priority), 1),
                _createElementVNode$3("td", null, _toDisplayString$4(row.name), 1),
                _createElementVNode$3("td", null, _toDisplayString$4(row.provider), 1),
                (__props.showCredentials)
                  ? (_openBlock$4(), _createElementBlock$2("td", _hoisted_3$3, _toDisplayString$4(row.base_url), 1))
                  : _createCommentVNode$2("", true),
                (__props.showCredentials)
                  ? (_openBlock$4(), _createElementBlock$2("td", _hoisted_4$2, _toDisplayString$4(getMaskedApiKey(index)), 1))
                  : _createCommentVNode$2("", true),
                _createElementVNode$3("td", null, [
                  _createVNode$4(_component_VChip, {
                    size: "small",
                    color: row.use_proxy === false ? 'default' : 'primary',
                    variant: "tonal"
                  }, {
                    default: _withCtx$4(() => [
                      _createTextVNode$4(_toDisplayString$4(row.use_proxy === false ? '直连' : '代理'), 1)
                    ]),
                    _: 2
                  }, 1032, ["color"])
                ]),
                _createElementVNode$3("td", null, _toDisplayString$4(row.model), 1),
                _createElementVNode$3("td", null, _toDisplayString$4(row.token_limit > 0 ? _unref$4(formatTokens)(row.token_limit) : '不限'), 1),
                _createElementVNode$3("td", _hoisted_5$2, [
                  _createVNode$4(_component_VBtn, {
                    icon: "mdi-pencil",
                    size: "small",
                    variant: "text",
                    onClick: $event => (emit('edit', index))
                  }, null, 8, ["onClick"]),
                  _createVNode$4(_component_VBtn, {
                    icon: "mdi-delete",
                    size: "small",
                    variant: "text",
                    color: "error",
                    onClick: $event => (emit('remove', index))
                  }, null, 8, ["onClick"])
                ])
              ]))
            }), 128)),
            (!__props.providers.length)
              ? (_openBlock$4(), _createElementBlock$2("tr", _hoisted_6$2, [
                  _createElementVNode$3("td", {
                    colspan: __props.showCredentials ? 10 : 8,
                    class: "text-center text-medium-emphasis py-8"
                  }, "暂无供应商", 8, _hoisted_7$2)
                ]))
              : _createCommentVNode$2("", true)
          ])
        ]),
        _: 1
      })
    ]),
    _: 1
  }))
}
}

};
const ProviderConfigTable = /*#__PURE__*/_export_sfc(_sfc_main$4, [['__scopeId',"data-v-cd4337d8"]]);

const {toDisplayString:_toDisplayString$3,createTextVNode:_createTextVNode$3,resolveComponent:_resolveComponent$3,withCtx:_withCtx$3,createVNode:_createVNode$3,unref:_unref$3,openBlock:_openBlock$3,createBlock:_createBlock$3} = await importShared('vue');


const {computed: computed$2} = await importShared('vue');


const _sfc_main$3 = {
  __name: 'ProviderEditorDialog',
  props: {
  modelValue: {
    type: Boolean,
    default: false,
  },
  provider: {
    type: Object,
    default: () => ({}),
  },
  editorIndex: {
    type: Number,
    default: -1,
  },
},
  emits: ['update:modelValue', 'commit'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const dialogVisible = computed$2({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
});

// 提交当前弹窗编辑的供应商配置。
function commitProvider() {
  emit('commit');
}

return (_ctx, _cache) => {
  const _component_VCardTitle = _resolveComponent$3("VCardTitle");
  const _component_VTextField = _resolveComponent$3("VTextField");
  const _component_VCol = _resolveComponent$3("VCol");
  const _component_VSelect = _resolveComponent$3("VSelect");
  const _component_VSwitch = _resolveComponent$3("VSwitch");
  const _component_VRow = _resolveComponent$3("VRow");
  const _component_VCardText = _resolveComponent$3("VCardText");
  const _component_VSpacer = _resolveComponent$3("VSpacer");
  const _component_VBtn = _resolveComponent$3("VBtn");
  const _component_VCardActions = _resolveComponent$3("VCardActions");
  const _component_VCard = _resolveComponent$3("VCard");
  const _component_VDialog = _resolveComponent$3("VDialog");

  return (_openBlock$3(), _createBlock$3(_component_VDialog, {
    modelValue: dialogVisible.value,
    "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((dialogVisible).value = $event)),
    "max-width": "760",
    "max-height": "85vh",
    scrollable: ""
  }, {
    default: _withCtx$3(() => [
      _createVNode$3(_component_VCard, null, {
        default: _withCtx$3(() => [
          _createVNode$3(_component_VCardTitle, null, {
            default: _withCtx$3(() => [
              _createTextVNode$3(_toDisplayString$3(__props.editorIndex >= 0 ? '编辑供应商' : '新增供应商'), 1)
            ]),
            _: 1
          }),
          _createVNode$3(_component_VCardText, null, {
            default: _withCtx$3(() => [
              _createVNode$3(_component_VRow, null, {
                default: _withCtx$3(() => [
                  _createVNode$3(_component_VCol, {
                    cols: "12",
                    md: "8"
                  }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.name,
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((__props.provider.name) = $event)),
                        label: "名称",
                        variant: "outlined",
                        density: "comfortable"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, {
                    cols: "12",
                    md: "4"
                  }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.priority,
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((__props.provider.priority) = $event)),
                        modelModifiers: { number: true },
                        label: "优先级",
                        type: "number",
                        variant: "outlined"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, {
                    cols: "12",
                    md: "6"
                  }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VSelect, {
                        modelValue: __props.provider.provider,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((__props.provider.provider) = $event)),
                        items: _unref$3(PROVIDER_TYPE_OPTIONS),
                        label: "类型",
                        variant: "outlined"
                      }, null, 8, ["modelValue", "items"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, {
                    cols: "12",
                    md: "6"
                  }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.model,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((__props.provider.model) = $event)),
                        label: "模型",
                        variant: "outlined"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, { cols: "12" }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.base_url,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((__props.provider.base_url) = $event)),
                        label: "API 地址",
                        variant: "outlined"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, { cols: "12" }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.api_key,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((__props.provider.api_key) = $event)),
                        label: "API Key",
                        type: "password",
                        variant: "outlined"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, { cols: "12" }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.user_agent,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((__props.provider.user_agent) = $event)),
                        label: "User-Agent",
                        variant: "outlined"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, { cols: "12" }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VSwitch, {
                        modelValue: __props.provider.use_proxy,
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((__props.provider.use_proxy) = $event)),
                        color: "primary",
                        label: "使用代理服务器",
                        hint: "启用后，Agent 连接该供应商时会使用系统代理服务器",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, {
                    cols: "12",
                    md: "6"
                  }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.token_limit,
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((__props.provider.token_limit) = $event)),
                        modelModifiers: { number: true },
                        label: "Token 额度",
                        type: "number",
                        variant: "outlined"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$3(_component_VCol, {
                    cols: "12",
                    md: "6"
                  }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_VTextField, {
                        modelValue: __props.provider.used_tokens,
                        "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((__props.provider.used_tokens) = $event)),
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
          _createVNode$3(_component_VCardActions, null, {
            default: _withCtx$3(() => [
              _createVNode$3(_component_VSpacer),
              _createVNode$3(_component_VBtn, {
                variant: "text",
                onClick: _cache[10] || (_cache[10] = $event => (dialogVisible.value = false))
              }, {
                default: _withCtx$3(() => [...(_cache[12] || (_cache[12] = [
                  _createTextVNode$3("取消", -1)
                ]))]),
                _: 1
              }),
              _createVNode$3(_component_VBtn, {
                color: "primary",
                onClick: commitProvider
              }, {
                default: _withCtx$3(() => [...(_cache[13] || (_cache[13] = [
                  _createTextVNode$3("确定", -1)
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
  }, 8, ["modelValue"]))
}
}

};

const {createElementVNode:_createElementVNode$2,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock$2,createElementBlock:_createElementBlock$1,toDisplayString:_toDisplayString$2,unref:_unref$2,resolveComponent:_resolveComponent$2,createVNode:_createVNode$2,createTextVNode:_createTextVNode$2,withCtx:_withCtx$2,createCommentVNode:_createCommentVNode$1,createBlock:_createBlock$2} = await importShared('vue');


const _hoisted_1$2 = { class: "progress-cell" };
const _hoisted_2$2 = { class: "text-right" };
const _hoisted_3$2 = { key: 0 };


const _sfc_main$2 = {
  __name: 'ProviderUsageTable',
  props: {
  providerRows: {
    type: Array,
    default: () => [],
  },
},
  emits: ['reset'],
  setup(__props, { emit: __emit }) {



const emit = __emit;

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

return (_ctx, _cache) => {
  const _component_VProgressLinear = _resolveComponent$2("VProgressLinear");
  const _component_VChip = _resolveComponent$2("VChip");
  const _component_VBtn = _resolveComponent$2("VBtn");
  const _component_VTable = _resolveComponent$2("VTable");
  const _component_VSheet = _resolveComponent$2("VSheet");

  return (_openBlock$2(), _createBlock$2(_component_VSheet, {
    border: "",
    rounded: "",
    class: "provider-table-shell"
  }, {
    default: _withCtx$2(() => [
      _createVNode$2(_component_VTable, { density: "comfortable" }, {
        default: _withCtx$2(() => [
          _cache[1] || (_cache[1] = _createElementVNode$2("thead", null, [
            _createElementVNode$2("tr", null, [
              _createElementVNode$2("th", null, "优先级"),
              _createElementVNode$2("th", null, "名称"),
              _createElementVNode$2("th", null, "模型"),
              _createElementVNode$2("th", null, "已用"),
              _createElementVNode$2("th", null, "余量"),
              _createElementVNode$2("th", null, "进度"),
              _createElementVNode$2("th", null, "状态"),
              _createElementVNode$2("th", { class: "text-right" }, "操作")
            ])
          ], -1)),
          _createElementVNode$2("tbody", null, [
            (_openBlock$2(true), _createElementBlock$1(_Fragment, null, _renderList(__props.providerRows, (row, index) => {
              return (_openBlock$2(), _createElementBlock$1("tr", {
                key: row.id || index
              }, [
                _createElementVNode$2("td", null, _toDisplayString$2(row.priority), 1),
                _createElementVNode$2("td", null, _toDisplayString$2(row.name), 1),
                _createElementVNode$2("td", null, _toDisplayString$2(row.model), 1),
                _createElementVNode$2("td", null, _toDisplayString$2(_unref$2(formatTokens)(row.usage?.total_tokens)), 1),
                _createElementVNode$2("td", null, _toDisplayString$2(row.usage?.remaining_tokens === null ? '不限' : _unref$2(formatTokens)(row.usage?.remaining_tokens)), 1),
                _createElementVNode$2("td", _hoisted_1$2, [
                  _createVNode$2(_component_VProgressLinear, {
                    "model-value": row.usage?.usage_percent || 0,
                    color: rowStatusColor(row),
                    height: "8",
                    rounded: ""
                  }, null, 8, ["model-value", "color"])
                ]),
                _createElementVNode$2("td", null, [
                  _createVNode$2(_component_VChip, {
                    size: "small",
                    color: rowStatusColor(row),
                    variant: "tonal"
                  }, {
                    default: _withCtx$2(() => [
                      _createTextVNode$2(_toDisplayString$2(rowStatusText(row)), 1)
                    ]),
                    _: 2
                  }, 1032, ["color"])
                ]),
                _createElementVNode$2("td", _hoisted_2$2, [
                  _createVNode$2(_component_VBtn, {
                    icon: "mdi-backup-restore",
                    size: "small",
                    variant: "text",
                    onClick: $event => (emit('reset', row.id, index))
                  }, null, 8, ["onClick"])
                ])
              ]))
            }), 128)),
            (!__props.providerRows.length)
              ? (_openBlock$2(), _createElementBlock$1("tr", _hoisted_3$2, [...(_cache[0] || (_cache[0] = [
                  _createElementVNode$2("td", {
                    colspan: "8",
                    class: "text-center text-medium-emphasis py-8"
                  }, "暂无供应商", -1)
                ]))]))
              : _createCommentVNode$1("", true)
          ])
        ]),
        _: 1
      })
    ]),
    _: 1
  }))
}
}

};
const ProviderUsageTable = /*#__PURE__*/_export_sfc(_sfc_main$2, [['__scopeId',"data-v-a305c97e"]]);

const {toDisplayString:_toDisplayString$1,createElementVNode:_createElementVNode$1,resolveComponent:_resolveComponent$1,withCtx:_withCtx$1,createVNode:_createVNode$1,unref:_unref$1,createTextVNode:_createTextVNode$1,openBlock:_openBlock$1,createBlock:_createBlock$1} = await importShared('vue');


const _hoisted_1$1 = { class: "usage-overview-card__content" };
const _hoisted_2$1 = { class: "usage-overview-card__chart" };
const _hoisted_3$1 = { class: "usage-overview-card__percent" };
const _hoisted_4$1 = { class: "usage-overview-card__body" };
const _hoisted_5$1 = { class: "usage-overview-card__headline" };
const _hoisted_6$1 = { class: "text-medium-emphasis" };
const _hoisted_7$1 = { class: "usage-overview-card__meta" };

const {computed: computed$1} = await importShared('vue');


const _sfc_main$1 = {
  __name: 'UsageOverviewCard',
  props: {
  summary: {
    type: Object,
    default: () => ({}),
  },
},
  setup(__props) {

const props = __props;

const totalUsed = computed$1(() => Number(props.summary.total_used || 0));
const totalLimit = computed$1(() => Number(props.summary.total_limit || 0));
const usagePercent = computed$1(() => {
  if (totalLimit.value <= 0) return 0
  return Math.min((totalUsed.value * 100) / totalLimit.value, 100)
});
const usagePercentText = computed$1(() => `${Math.round(usagePercent.value)}%`);
const remainingTokens = computed$1(() => {
  if (totalLimit.value <= 0) return null
  return Math.max(totalLimit.value - totalUsed.value, 0)
});
const progressColor = computed$1(() => {
  if (totalLimit.value <= 0) return 'primary'
  if (usagePercent.value >= 90) return 'error'
  if (usagePercent.value >= 70) return 'warning'
  return 'success'
});

return (_ctx, _cache) => {
  const _component_VProgressCircular = _resolveComponent$1("VProgressCircular");
  const _component_VProgressLinear = _resolveComponent$1("VProgressLinear");
  const _component_VSheet = _resolveComponent$1("VSheet");

  return (_openBlock$1(), _createBlock$1(_component_VSheet, {
    border: "",
    rounded: "",
    class: "usage-overview-card"
  }, {
    default: _withCtx$1(() => [
      _createElementVNode$1("div", _hoisted_1$1, [
        _createElementVNode$1("div", _hoisted_2$1, [
          _createVNode$1(_component_VProgressCircular, {
            "model-value": usagePercent.value,
            color: progressColor.value,
            "bg-color": "surface-variant",
            size: 132,
            width: 12
          }, {
            default: _withCtx$1(() => [
              _createElementVNode$1("div", _hoisted_3$1, _toDisplayString$1(totalLimit.value > 0 ? usagePercentText.value : '不限'), 1)
            ]),
            _: 1
          }, 8, ["model-value", "color"])
        ]),
        _createElementVNode$1("div", _hoisted_4$1, [
          _cache[0] || (_cache[0] = _createElementVNode$1("div", { class: "text-caption text-medium-emphasis" }, "总使用进度", -1)),
          _createElementVNode$1("div", _hoisted_5$1, [
            _createTextVNode$1(_toDisplayString$1(_unref$1(formatTokens)(totalUsed.value)) + " ", 1),
            _createElementVNode$1("span", _hoisted_6$1, "/ " + _toDisplayString$1(totalLimit.value > 0 ? _unref$1(formatTokens)(totalLimit.value) : '不限'), 1)
          ]),
          _createVNode$1(_component_VProgressLinear, {
            "model-value": usagePercent.value,
            color: progressColor.value,
            height: "8",
            rounded: "",
            class: "my-4"
          }, null, 8, ["model-value", "color"]),
          _createElementVNode$1("div", _hoisted_7$1, [
            _createElementVNode$1("span", null, "剩余 " + _toDisplayString$1(remainingTokens.value === null ? '不限' : _unref$1(formatTokens)(remainingTokens.value)), 1),
            _createElementVNode$1("span", null, "可用 " + _toDisplayString$1(__props.summary.available_count || 0) + " / " + _toDisplayString$1(__props.summary.enabled_count || 0), 1)
          ])
        ])
      ])
    ]),
    _: 1
  }))
}
}

};
const UsageOverviewCard = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-f9b76345"]]);

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,createBlock:_createBlock,unref:_unref} = await importShared('vue');


const _hoisted_1 = { class: "agenttokens-page" };
const _hoisted_2 = {
  key: 0,
  class: "agenttokens-header"
};
const _hoisted_3 = { class: "agenttokens-control-panel__switches" };
const _hoisted_4 = { class: "agenttokens-overview-grid" };
const _hoisted_5 = { class: "agenttokens-stat-card__value" };
const _hoisted_6 = { class: "agenttokens-stat-card__value" };
const _hoisted_7 = { class: "agenttokens-stat-card__value" };
const _hoisted_8 = { class: "agenttokens-tabs-row" };
const _hoisted_9 = { class: "agenttokens-table-actions" };

const {computed,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'AgentTokensManager',
  props: {
  config: {
    type: Object,
    default: () => ({ enabled: false, show_sidebar_nav: true, providers: [] }),
  },
  providerRows: {
    type: Array,
    default: () => [],
  },
  summary: {
    type: Object,
    default: () => ({}),
  },
  error: {
    type: String,
    default: '',
  },
  loading: {
    type: Boolean,
    default: false,
  },
  saving: {
    type: Boolean,
    default: false,
  },
  hideTitle: {
    type: Boolean,
    default: false,
  },
},
  emits: ['refresh', 'save', 'reset-usage', 'reset-all-usage'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const activeTab = ref('usage');
const showEditor = ref(false);
const editorIndex = ref(-1);
const editedProvider = ref(createProvider());

const configValue = computed(() => props.config || { enabled: false, show_sidebar_nav: true, providers: [] });
const providers = computed(() => (Array.isArray(configValue.value.providers) ? configValue.value.providers : []));
const displayProviderRows = computed(() => (
  props.providerRows.length ? props.providerRows : buildProviderRows(providers.value)
));
const displaySummary = computed(() => (
  Object.keys(props.summary || {}).length ? props.summary : buildProviderSummary(displayProviderRows.value)
));

// 打开新增供应商弹窗。
function addProvider() {
  editedProvider.value = { ...createProvider(), priority: getNextProviderPriority(providers.value) };
  editorIndex.value = -1;
  showEditor.value = true;
}

// 打开编辑供应商弹窗。
function editProvider(index) {
  editedProvider.value = { ...providers.value[index] };
  editorIndex.value = index;
  showEditor.value = true;
}

// 将弹窗中的供应商写回配置列表。
function commitProvider() {
  const nextProviders = [...providers.value];
  const normalized = normalizeProvider(editedProvider.value, nextProviders.length + 1);
  if (editorIndex.value >= 0) {
    nextProviders.splice(editorIndex.value, 1, normalized);
  } else {
    nextProviders.push(normalized);
  }
  configValue.value.providers = nextProviders;
  showEditor.value = false;
}

// 从配置列表中移除一个供应商。
function removeProvider(index) {
  const nextProviders = [...providers.value];
  nextProviders.splice(index, 1);
  configValue.value.providers = nextProviders;
}

// 请求重置单个供应商用量。
function resetUsage(providerId, index) {
  emit('reset-usage', providerId, index);
}

// 请求重置全部供应商用量。
function resetAllUsage() {
  emit('reset-all-usage');
}

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VSheet = _resolveComponent("VSheet");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VTab = _resolveComponent("VTab");
  const _component_VTabs = _resolveComponent("VTabs");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VWindowItem = _resolveComponent("VWindowItem");
  const _component_VWindow = _resolveComponent("VWindow");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (!__props.hideTitle)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, [
          _cache[7] || (_cache[7] = _createElementVNode("h2", { class: "text-2xl font-bold leading-7 text-gray-100 truncate sm:text-3xl sm:leading-9" }, [
            _createElementVNode("span", { class: "text-moviepilot" }, "Agent Tokens 管理")
          ], -1)),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            icon: "mdi-refresh",
            variant: "text",
            loading: __props.loading,
            onClick: _cache[0] || (_cache[0] = $event => (emit('refresh')))
          }, null, 8, ["loading"]),
          _createVNode(_component_VBtn, {
            icon: "mdi-content-save",
            variant: "text",
            color: "primary",
            loading: __props.saving,
            onClick: _cache[1] || (_cache[1] = $event => (emit('save')))
          }, null, 8, ["loading"])
        ]))
      : _createCommentVNode("", true),
    (__props.error)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "error",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(__props.error), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_VSheet, {
      border: "",
      rounded: "",
      class: "agenttokens-control-panel"
    }, {
      default: _withCtx(() => [
        _createElementVNode("div", _hoisted_3, [
          _createVNode(_component_VSwitch, {
            modelValue: configValue.value.enabled,
            "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((configValue.value.enabled) = $event)),
            color: "primary",
            "hide-details": "",
            inset: "",
            label: "启用插件"
          }, null, 8, ["modelValue"]),
          _createVNode(_component_VSwitch, {
            modelValue: configValue.value.show_sidebar_nav,
            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((configValue.value.show_sidebar_nav) = $event)),
            color: "primary",
            "hide-details": "",
            inset: "",
            label: "侧边栏入口"
          }, null, 8, ["modelValue"])
        ])
      ]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_4, [
      _createVNode(UsageOverviewCard, {
        class: "agenttokens-overview-card",
        summary: displaySummary.value
      }, null, 8, ["summary"]),
      _createVNode(_component_VSheet, {
        border: "",
        rounded: "",
        class: "agenttokens-stat-card"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VIcon, {
            icon: "mdi-check-decagram-outline",
            color: "success"
          }),
          _createElementVNode("div", null, [
            _cache[8] || (_cache[8] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "可用供应商", -1)),
            _createElementVNode("div", _hoisted_5, _toDisplayString(displaySummary.value.available_count || 0) + " / " + _toDisplayString(displaySummary.value.enabled_count || 0), 1)
          ])
        ]),
        _: 1
      }),
      _createVNode(_component_VSheet, {
        border: "",
        rounded: "",
        class: "agenttokens-stat-card"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VIcon, {
            icon: "mdi-chart-timeline-variant",
            color: "primary"
          }),
          _createElementVNode("div", null, [
            _cache[9] || (_cache[9] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "累计使用", -1)),
            _createElementVNode("div", _hoisted_6, _toDisplayString(_unref(formatTokens)(displaySummary.value.total_used)), 1)
          ])
        ]),
        _: 1
      }),
      _createVNode(_component_VSheet, {
        border: "",
        rounded: "",
        class: "agenttokens-stat-card"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VIcon, {
            icon: "mdi-database-outline",
            color: "info"
          }),
          _createElementVNode("div", null, [
            _cache[10] || (_cache[10] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "总额度", -1)),
            _createElementVNode("div", _hoisted_7, _toDisplayString(displaySummary.value.total_limit ? _unref(formatTokens)(displaySummary.value.total_limit) : '不限'), 1)
          ])
        ]),
        _: 1
      })
    ]),
    _createVNode(_component_VSheet, {
      border: "",
      rounded: "",
      class: "agenttokens-content-panel"
    }, {
      default: _withCtx(() => [
        _createElementVNode("div", _hoisted_8, [
          _createVNode(_component_VTabs, {
            modelValue: activeTab.value,
            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((activeTab).value = $event)),
            density: "comfortable"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VTab, { value: "usage" }, {
                default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                  _createTextVNode("用量", -1)
                ]))]),
                _: 1
              }),
              _createVNode(_component_VTab, { value: "config" }, {
                default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                  _createTextVNode("配置", -1)
                ]))]),
                _: 1
              })
            ]),
            _: 1
          }, 8, ["modelValue"])
        ]),
        _createVNode(_component_VDivider),
        _createVNode(_component_VWindow, {
          modelValue: activeTab.value,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((activeTab).value = $event)),
          touch: false,
          class: "agenttokens-window"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VWindowItem, { value: "usage" }, {
              default: _withCtx(() => [
                _createVNode(ProviderUsageTable, {
                  "provider-rows": displayProviderRows.value,
                  onReset: resetUsage
                }, null, 8, ["provider-rows"])
              ]),
              _: 1
            }),
            _createVNode(_component_VWindowItem, { value: "config" }, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_9, [
                  _createVNode(_component_VBtn, {
                    "prepend-icon": "mdi-plus",
                    color: "primary",
                    variant: "tonal",
                    onClick: addProvider
                  }, {
                    default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                      _createTextVNode("新增", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    "prepend-icon": "mdi-backup-restore",
                    color: "warning",
                    variant: "tonal",
                    onClick: resetAllUsage
                  }, {
                    default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                      _createTextVNode(" 重置用量 ", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _createVNode(ProviderConfigTable, {
                  providers: providers.value,
                  "provider-rows": displayProviderRows.value,
                  "show-credentials": "",
                  onEdit: editProvider,
                  onRemove: removeProvider
                }, null, 8, ["providers", "provider-rows"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["modelValue"])
      ]),
      _: 1
    }),
    _createVNode(_sfc_main$3, {
      modelValue: showEditor.value,
      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((showEditor).value = $event)),
      provider: editedProvider.value,
      "editor-index": editorIndex.value,
      onCommit: commitProvider
    }, null, 8, ["modelValue", "provider", "editor-index"])
  ]))
}
}

};
const AgentTokensManager = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-a6c1ea54"]]);

export { AgentTokensManager as A };
