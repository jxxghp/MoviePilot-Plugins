import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = {
  key: 1,
  class: "text-caption text-medium-emphasis mb-2"
};

const {ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'ZSpaceVideo' },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;

const DEFAULTS = {
  enabled: false,
  connection_mode: 'cloud',
  lan_host: '',
  path_mapping: '',
  library_dirs: '',
  zvideo_db: '/zvideo/zvideo.db',
  quiet_seconds: 60,
  max_wait_seconds: 300,
  poll_timeout_seconds: 1800,
  notify: true,
  watched_enabled: false,
  watched_auto_mode: 'none',
  watched_buffer_days: 7,
  watched_sync_minutes: 60,
  watched_auto_since: 0,
};
const form = ref({ ...DEFAULTS, ...(props.initialConfig || {}) });
watch(() => props.initialConfig, v => { form.value = { ...DEFAULTS, ...(v || {}) }; });

const deleteModes = [
  { title: '不删（默认）', value: 'none' },
  { title: '只从库里移除（继续做种，不腾空间）', value: 'library' },
  { title: '真删除（库入口 + 做种文件 + qB 任务，腾出空间）', value: 'full' },
];

const modes = [
  { title: '官方云中转（默认，HTTPS）', value: 'cloud' },
  { title: '局域网 HTTP 直连', value: 'lan' },
];

function save() {
  const payload = { ...form.value };
  for (const k of ['quiet_seconds', 'max_wait_seconds', 'poll_timeout_seconds', 'watched_sync_minutes']) payload[k] = Number(payload[k]) || DEFAULTS[k];
  payload.watched_buffer_days = Number(payload.watched_buffer_days);
  if (!(payload.watched_buffer_days >= 1)) payload.watched_buffer_days = DEFAULTS.watched_buffer_days;
  emit('save', payload);
}

return (_ctx, _cache) => {
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createBlock(_component_VCard, null, {
    default: _withCtx(() => [
      _createVNode(_component_VCardItem, null, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, null, {
            default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
              _createTextVNode("极空间影视 · 设置", -1)
            ]))]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCardText, null, {
        default: _withCtx(() => [
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSwitch, {
                    modelValue: form.value.enabled,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((form.value.enabled) = $event)),
                    label: "启用",
                    color: "primary",
                    "hide-details": ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCol, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSwitch, {
                    modelValue: form.value.notify,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((form.value.notify) = $event)),
                    label: "刷新失败发站内消息（同类问题只提醒一次）",
                    color: "primary",
                    "hide-details": ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSelect, {
                    modelValue: form.value.connection_mode,
                    "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.value.connection_mode) = $event)),
                    items: modes,
                    label: "连接方式"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              (form.value.connection_mode === 'lan')
                ? (_openBlock(), _createBlock(_component_VCol, {
                    key: 0,
                    cols: "12",
                    md: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VTextField, {
                        modelValue: form.value.lan_host,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.value.lan_host) = $event)),
                        label: "极空间地址",
                        placeholder: "http://nas.example.com:5055"
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }))
                : _createCommentVNode("", true)
            ]),
            _: 1
          }),
          (form.value.connection_mode === 'lan')
            ? (_openBlock(), _createBlock(_component_VAlert, {
                key: 0,
                type: "warning",
                variant: "tonal",
                class: "mb-4"
              }, {
                default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                  _createTextVNode(" 局域网直连走明文 HTTP：访问令牌会以明文经过家里网络，同网段的设备能截获它， 拿到后可以在令牌有效期内以你的极空间账号调用接口。只在你信任家里所有设备时用； 好处是不经过极空间云端，云端故障时也能刷新。 ", -1)
                ]))]),
                _: 1
              }))
            : _createCommentVNode("", true),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextarea, {
                    modelValue: form.value.path_mapping,
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((form.value.path_mapping) = $event)),
                    rows: "3",
                    "auto-grow": "",
                    label: "路径映射（留空自动推断）",
                    placeholder: "/downloads => /sata1/my/data/downloads",
                    hint: "每行「容器里的路径 => 极空间里的路径」。留空时按 MoviePilot 容器的挂载自动推断。",
                    "persistent-hint": ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextarea, {
                    modelValue: form.value.library_dirs,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.value.library_dirs) = $event)),
                    rows: "3",
                    "auto-grow": "",
                    label: "分类目录（留空读极影视库）",
                    placeholder: "动漫 = /sata1/my/data/downloads/anime",
                    hint: "每行「分类名或ID = 极空间目录」。留空时从只读挂载的极影视库读取（需把 /zspace/zsrp/sqlite/zvideo 只读挂到 /zvideo）。",
                    "persistent-hint": ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.value.quiet_seconds,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.value.quiet_seconds) = $event)),
                    type: "number",
                    label: "去抖：安静多少秒后提交"
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
                    modelValue: form.value.max_wait_seconds,
                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.value.max_wait_seconds) = $event)),
                    type: "number",
                    label: "最多攒多少秒"
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
                    modelValue: form.value.poll_timeout_seconds,
                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((form.value.poll_timeout_seconds) = $event)),
                    type: "number",
                    label: "等待扫描结果上限（秒）"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.value.zvideo_db,
                    "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((form.value.zvideo_db) = $event)),
                    label: "极影视库路径（只读）"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VDivider, { class: "my-4" }),
          _cache[20] || (_cache[20] = _createElementVNode("div", { class: "text-subtitle-1 mb-2" }, "已看", -1)),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSwitch, {
                    modelValue: form.value.watched_enabled,
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((form.value.watched_enabled) = $event)),
                    label: "定时读取极影视已看",
                    color: "primary",
                    "hide-details": ""
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
                    modelValue: form.value.watched_sync_minutes,
                    "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((form.value.watched_sync_minutes) = $event)),
                    type: "number",
                    label: "每隔多少分钟读一次",
                    disabled: !form.value.watched_enabled
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "8"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSelect, {
                    modelValue: form.value.watched_auto_mode,
                    "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((form.value.watched_auto_mode) = $event)),
                    items: deleteModes,
                    label: "自动删除",
                    disabled: !form.value.watched_enabled
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCol, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.value.watched_buffer_days,
                    "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((form.value.watched_buffer_days) = $event)),
                    type: "number",
                    min: "1",
                    label: "已看满多少天后执行（缓冲期，至少 1 天）",
                    disabled: !form.value.watched_enabled || form.value.watched_auto_mode === 'none'
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          (form.value.watched_auto_mode !== 'none')
            ? (_openBlock(), _createElementBlock("p", _hoisted_1, " 只处理打开自动删除之后才看完的；之前已经看过的留在已看列表里，要删请手动。 "))
            : _createCommentVNode("", true),
          (form.value.watched_auto_mode === 'full')
            ? (_openBlock(), _createBlock(_component_VAlert, {
                key: 2,
                type: "error",
                variant: "tonal",
                class: "mb-2"
              }, {
                default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                  _createTextVNode(" 真删除会删掉下载目录里做种的文件和 qB 任务（含辅种），删了只能重新下载。缓冲期内在极影视里取消「已看过」就不会删。 ", -1)
                ]))]),
                _: 1
              }))
            : (form.value.watched_auto_mode === 'library')
              ? (_openBlock(), _createBlock(_component_VAlert, {
                  key: 3,
                  type: "info",
                  variant: "tonal",
                  class: "mb-2"
                }, {
                  default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                    _createTextVNode(" 只删库里的入口，继续做种，不腾空间；极影视里这部片会消失。 ", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true)
        ]),
        _: 1
      }),
      _createVNode(_component_VCardActions, null, {
        default: _withCtx(() => [
          _createVNode(_component_VBtn, {
            variant: "text",
            onClick: _cache[14] || (_cache[14] = $event => (emit('switch')))
          }, {
            default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
              _createTextVNode("查看状态", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            variant: "text",
            onClick: _cache[15] || (_cache[15] = $event => (emit('close')))
          }, {
            default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
              _createTextVNode("取消", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            color: "primary",
            variant: "flat",
            onClick: save
          }, {
            default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
              _createTextVNode("保存", -1)
            ]))]),
            _: 1
          })
        ]),
        _: 1
      })
    ]),
    _: 1
  }))
}
}

};

export { _sfc_main as default };
