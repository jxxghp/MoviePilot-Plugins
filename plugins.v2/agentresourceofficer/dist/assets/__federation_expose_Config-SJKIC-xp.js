import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const CLIENT_TYPES = [
  { title: '支付宝', label: '支付宝', value: 'alipaymini' },
  { title: '微信', label: '微信', value: 'wechatmini' },
  { title: '安卓', label: '安卓', value: '115android' },
  { title: 'iOS', label: 'iOS', value: '115ios' },
  { title: '网页', label: '网页', value: 'web' },
  { title: 'PAD', label: 'PAD', value: '115ipad' },
  { title: 'TV', label: 'TV', value: 'tv' },
];

function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config || {}))
}

function unwrapResponse(response) {
  if (!response) return response
  if (Object.prototype.hasOwnProperty.call(response, 'success')) return response
  if (Object.prototype.hasOwnProperty.call(response, 'data')) return response.data
  return response
}

function maskSecret(value, visible) {
  const text = String(value || '');
  if (visible || !text) return text
  return '•'.repeat(Math.min(Math.max(text.length, 8), 24))
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,unref:_unref,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "aro-config" };
const _hoisted_2 = { class: "aro-body" };
const _hoisted_3 = { class: "aro-inner" };
const _hoisted_4 = { class: "aro-intro text-body-2 mb-3" };
const _hoisted_5 = {
  key: 1,
  class: "d-flex flex-column align-center py-3"
};
const _hoisted_6 = {
  key: 2,
  class: "d-flex flex-column align-center"
};
const _hoisted_7 = { class: "d-flex flex-column align-center mb-3" };
const _hoisted_8 = ["src"];
const _hoisted_9 = { class: "text-body-2 text-grey mb-1" };
const _hoisted_10 = { class: "text-subtitle-2 font-weight-medium text-primary" };
const _hoisted_11 = {
  key: 3,
  class: "d-flex flex-column align-center py-3"
};

const {computed,onBeforeUnmount,onMounted,reactive,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'AgentResourceOfficer',
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const config = ref({});
const message = reactive({ text: '', type: 'info' });
const showCookie = ref(false);
const showFeishuSecret = ref(false);
const showHdhiveApiKey = ref(false);
const showHdhiveAccessToken = ref(false);
const showHdhiveRefreshToken = ref(false);
const showHdhiveCookie = ref(false);
const showHdhivePassword = ref(false);
const saving = ref(false);
const healthLoading = ref(false);
const health = ref(null);

const qr = reactive({
  show: false,
  loading: false,
  error: '',
  qrcode: '',
  uid: '',
  time: '',
  sign: '',
  tips: '请使用 115 客户端扫描二维码登录',
  status: '等待扫码',
  clientType: 'alipaymini',
  timer: null,
  requestId: 0,
  checking: false,
});

const pluginBase = computed(() => `plugin/${props.pluginId || 'AgentResourceOfficer'}`);
const p115ReadyText = computed(() => {
  if (!health.value) return config.value.p115_cookie ? '已配置 Cookie' : '未检测'
  if (health.value.p115_ready) return '115 可用'
  return health.value.message || '115 未就绪'
});

function enableChip(value) {
  return value
    ? { text: '已启用', color: 'success' }
    : { text: '未启用', color: 'grey' }
}

function showMessage(text, type = 'info') {
  message.text = text;
  message.type = type;
  if (text) {
    setTimeout(() => {
      if (message.text === text) message.text = '';
    }, 3500);
  }
}

async function persistConfig({ silent = false } = {}) {
  saving.value = true;
  try {
    const response = await withTimeout(
      props.api.post(`${pluginBase.value}/config/save`, cloneConfig(config.value)),
      12000,
      '保存配置超时，请稍后重试'
    );
    const result = unwrapResponse(response);
    if (!result?.success) {
      throw new Error(result?.message || '保存配置失败')
    }
    if (result.data) {
      config.value = cloneConfig(result.data);
    }
    emit('save', cloneConfig(config.value));
    if (!silent) showMessage(result.message || '配置已保存', 'success');
    return true
  } catch (err) {
    if (!silent) showMessage(err?.message || '保存配置失败', 'error');
    return false
  } finally {
    saving.value = false;
  }
}

function saveConfig() {
  persistConfig();
}

async function copyText(value, label) {
  try {
    await navigator.clipboard.writeText(String(value || ''));
    showMessage(`${label} 已复制`, 'success');
  } catch (err) {
    showMessage('复制失败，请手动复制', 'error');
  }
}

function clearQrTimer() {
  if (qr.timer) {
    clearInterval(qr.timer);
    qr.timer = null;
  }
}

function applyQrData(data) {
  qr.qrcode = data?.qrcode || '';
  qr.uid = data?.uid || '';
  qr.time = data?.time || '';
  qr.sign = data?.sign || '';
  qr.tips = data?.tips || '请使用 115 客户端扫描二维码登录';
  qr.status = '等待扫码';
}

function withTimeout(promise, ms, message) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(message)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId))
}

async function requestQrCode() {
  const requestId = qr.requestId + 1;
  qr.requestId = requestId;
  qr.loading = true;
  qr.error = '';
  qr.qrcode = '';
  qr.uid = '';
  qr.time = '';
  qr.sign = '';
  clearQrTimer();
  try {
    const response = await withTimeout(
      props.api.get(`${pluginBase.value}/p115/ui/qrcode?client_type=${encodeURIComponent(qr.clientType)}`),
      12000,
      '获取二维码超时，请稍后重试'
    );
    if (requestId !== qr.requestId || !qr.show) return
    const result = unwrapResponse(response);
    if (!result?.success || !result?.data) {
      throw new Error(result?.message || '获取二维码失败')
    }
    applyQrData(result.data);
    qr.timer = setInterval(() => checkQrCode(requestId), 3000);
  } catch (err) {
    if (requestId !== qr.requestId) return
    qr.error = err?.message || '获取二维码失败';
    qr.status = '二维码获取失败';
  } finally {
    if (requestId === qr.requestId) {
      qr.loading = false;
    }
  }
}

async function checkQrCode(requestId = qr.requestId) {
  if (!qr.show || !qr.uid || !qr.time || !qr.sign) return
  if (requestId !== qr.requestId || qr.checking) return
  qr.checking = true;
  try {
    const query = new URLSearchParams({
      uid: qr.uid,
      time: qr.time,
      sign: qr.sign,
      client_type: qr.clientType,
    });
    const response = await withTimeout(
      props.api.get(`${pluginBase.value}/p115/ui/qrcode/check?${query.toString()}`),
      10000,
      '检查二维码状态超时'
    );
    if (requestId !== qr.requestId || !qr.show) return
    const result = unwrapResponse(response);
    const data = result?.data || {};
    if (!result?.success) {
      if (data.status === 'expired') {
        clearQrTimer();
        qr.status = '二维码已失效';
        qr.error = result?.message || '二维码已失效，请刷新';
      }
      return
    }
    if (data.status === 'waiting') qr.status = '等待扫码';
    if (data.status === 'scanned') qr.status = '已扫码，请在设备上确认';
    if (data.status === 'expired') {
      clearQrTimer();
      qr.status = '二维码已失效';
      qr.error = '二维码已失效，请刷新';
    }
    if (data.status === 'success') {
      clearQrTimer();
      qr.status = '登录成功';
      if (data.cookie_saved) {
        config.value.p115_client_type = qr.clientType;
        if (data.cookie) config.value.p115_cookie = data.cookie;
        await persistConfig({ silent: true });
      }
      showMessage('115 登录成功，Cookie 已自动保存。', 'success');
      setTimeout(() => {
        qr.show = false;
      }, 1800);
      await loadP115Health();
    }
  } catch (err) {
    console.error('检查 115 二维码状态失败:', err);
  } finally {
    if (requestId === qr.requestId) {
      qr.checking = false;
    }
  }
}

function openQrDialog() {
  qr.show = true;
  qr.error = '';
  qr.status = '等待扫码';
  qr.clientType = config.value.p115_client_type || 'alipaymini';
  requestQrCode();
}

function closeQrDialog() {
  clearQrTimer();
  qr.requestId += 1;
  qr.loading = false;
  qr.checking = false;
  qr.show = false;
}

async function refreshQrCode() {
  qr.error = '';
  await requestQrCode();
}

async function changeQrClientType(value) {
  if (!value || value === qr.clientType) return
  qr.clientType = value;
  qr.error = '';
  await requestQrCode();
}

async function loadP115Health() {
  if (!props.api?.get) return
  healthLoading.value = true;
  try {
    const response = await props.api.get(`${pluginBase.value}/p115/ui/health`);
    const result = unwrapResponse(response);
    if (result?.success) {
      health.value = result.data || null;
    }
  } catch (err) {
    health.value = { p115_ready: false, message: err?.message || '检测失败' };
  } finally {
    healthLoading.value = false;
  }
}

async function loadLatestConfig() {
  if (!props.api?.get) return false
  try {
    const response = await withTimeout(
      props.api.get(`${pluginBase.value}/config/get`),
      12000,
      '加载配置超时'
    );
    const result = unwrapResponse(response);
    if (result?.success && result.data) {
      config.value = cloneConfig(result.data);
      if (!config.value.p115_client_type) config.value.p115_client_type = 'alipaymini';
      return true
    }
  } catch (err) {
    console.error('加载 Agent影视助手 配置失败:', err);
  }
  return false
}

onMounted(async () => {
  config.value = cloneConfig(props.initialConfig);
  if (!config.value.p115_client_type) config.value.p115_client_type = 'alipaymini';
  await loadLatestConfig();
  loadP115Health();
});

onBeforeUnmount(clearQrTimer);

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardSubtitle = _resolveComponent("VCardSubtitle");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VProgressCircular = _resolveComponent("VProgressCircular");
  const _component_VChipGroup = _resolveComponent("VChipGroup");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      color: "transparent",
      class: "aro-toolbar"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VIcon, {
          icon: "mdi-robot-outline",
          color: "primary",
          class: "ms-3 me-2"
        }),
        _cache[55] || (_cache[55] = _createElementVNode("div", { class: "text-h6" }, "Agent影视助手配置", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-refresh",
          variant: "text",
          loading: healthLoading.value,
          title: "刷新 115 状态",
          onClick: loadP115Health
        }, null, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-content-save",
          variant: "text",
          color: "success",
          loading: saving.value,
          title: "保存配置",
          onClick: saveConfig
        }, null, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          title: "关闭",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        (message.text)
          ? (_openBlock(), _createBlock(_component_VAlert, {
              key: 0,
              type: message.type,
              variant: "tonal",
              density: "compact",
              closable: "",
              class: "mb-3"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(message.text), 1)
              ]),
              _: 1
            }, 8, ["type"]))
          : _createCommentVNode("", true),
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_VIcon, {
            icon: "mdi-rocket-launch-outline",
            size: "small",
            color: "primary",
            class: "me-1"
          }),
          _cache[56] || (_cache[56] = _createElementVNode("span", null, "快速开始：先启用插件并配置 MP/PT，再按需开启影巢、盘搜与飞书入口；完整说明见", -1)),
          _cache[57] || (_cache[57] = _createElementVNode("a", {
            href: "https://github.com/liuyuexi1987/MoviePilot-Plugins",
            target: "_blank",
            rel: "noopener",
            class: "text-primary text-decoration-none font-weight-medium"
          }, "主页文档", -1)),
          _cache[58] || (_cache[58] = _createTextVNode("。 ", -1))
        ]),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-toggle-switch",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: enableChip(config.value.enabled).color,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(enableChip(config.value.enabled).text), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[59] || (_cache[59] = [
                    _createTextVNode("基础设置", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[60] || (_cache[60] = [
                    _createTextVNode("启用插件、通知与调试开关", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.enabled,
                          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.value.enabled) = $event)),
                          label: "启用插件",
                          color: "success",
                          density: "compact",
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
                          modelValue: config.value.notify,
                          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.value.notify) = $event)),
                          label: "发送通知",
                          color: "success",
                          density: "compact",
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
                          modelValue: config.value.debug,
                          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.value.debug) = $event)),
                          label: "调试日志",
                          color: "warning",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
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
        }),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-movie-search-outline",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: enableChip(config.value.mp_pt_enabled).color,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(enableChip(config.value.mp_pt_enabled).text), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[61] || (_cache[61] = [
                    _createTextVNode("MP/PT 策略", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[62] || (_cache[62] = [
                    _createTextVNode("首选主线：原生搜索/订阅/下载；评分仅影响未保存偏好的新会话", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.mp_pt_enabled,
                          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.value.mp_pt_enabled) = $event)),
                          label: "启用 MP/PT",
                          color: "success",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.assistant_default_pt_min_seeders,
                          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.value.assistant_default_pt_min_seeders) = $event)),
                          label: "最低做种数",
                          type: "number",
                          placeholder: "3",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.assistant_default_confirm_score_threshold,
                          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.value.assistant_default_confirm_score_threshold) = $event)),
                          label: "建议确认分",
                          type: "number",
                          placeholder: "70",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.assistant_default_auto_ingest_score_threshold,
                          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.value.assistant_default_auto_ingest_score_threshold) = $event)),
                          label: "自动入库分",
                          type: "number",
                          placeholder: "90",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.assistant_default_auto_ingest_enabled,
                          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.value.assistant_default_auto_ingest_enabled) = $event)),
                          label: "高分自动入库",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "9"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.mp_download_save_path,
                          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.value.mp_download_save_path) = $event)),
                          label: "PT 下载保存路径（可选）",
                          placeholder: "默认留空；需要时填 local:/downloads 等",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
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
        }),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-cloud-lock-outline",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: health.value?.p115_ready ? 'success' : 'warning',
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(p115ReadyText.value), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[63] || (_cache[63] = [
                    _createTextVNode("115 扫码登录", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[64] || (_cache[64] = [
                    _createTextVNode("扫码写入 Cookie，手填仅作兜底", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, {
                  dense: "",
                  align: "center"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.p115_default_path,
                          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.value.p115_default_path) = $event)),
                          label: "115 默认目录",
                          placeholder: "/待整理",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSelect, {
                          modelValue: config.value.p115_client_type,
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.value.p115_client_type) = $event)),
                          items: _unref(CLIENT_TYPES),
                          "item-title": "title",
                          "item-value": "value",
                          label: "智能体扫码默认客户端",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue", "items"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.p115_prefer_direct,
                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.value.p115_prefer_direct) = $event)),
                          label: "优先 115 直转",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          "model-value": _unref(maskSecret)(config.value.p115_cookie, showCookie.value),
                          label: "115 Cookie",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto",
                          readonly: "",
                          hint: "点击右侧二维码图标扫码，成功后自动保存 Cookie。",
                          "persistent-hint": ""
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showCookie.value ? 'mdi-eye-off' : 'mdi-eye',
                              class: "me-2",
                              size: "small",
                              onClick: _cache[13] || (_cache[13] = $event => (showCookie.value = !showCookie.value))
                            }, null, 8, ["icon"]),
                            _createVNode(_component_VIcon, {
                              icon: "mdi-content-copy",
                              class: "me-2",
                              size: "small",
                              disabled: !config.value.p115_cookie,
                              onClick: _cache[14] || (_cache[14] = $event => (copyText(config.value.p115_cookie, '115 Cookie')))
                            }, null, 8, ["disabled"])
                          ]),
                          append: _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: "mdi-qrcode-scan",
                              color: config.value.p115_cookie ? 'success' : 'primary',
                              title: "扫码获取或更新 115 Cookie",
                              onClick: openQrDialog
                            }, null, 8, ["color"])
                          ]),
                          _: 1
                        }, 8, ["model-value"])
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
        }),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-honeycomb-outline",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: enableChip(config.value.hdhive_resource_enabled).color,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(enableChip(config.value.hdhive_resource_enabled).text), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[65] || (_cache[65] = [
                    _createTextVNode("影巢资源", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
                    _createTextVNode("资源搜索 / 解锁 / 转存；积分上限填 0 不限制", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.hdhive_resource_enabled,
                          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.value.hdhive_resource_enabled) = $event)),
                          label: "启用搜索/解锁",
                          color: "success",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSelect, {
                          modelValue: config.value.hdhive_resource_mode,
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((config.value.hdhive_resource_mode) = $event)),
                          items: [
                  { title: '网页方式', value: 'browser' },
                  { title: 'OpenAPI', value: 'openapi' },
                  { title: '自动(网页优先)', value: 'auto' },
                ],
                          "item-title": "title",
                          "item-value": "value",
                          label: "资源方式",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_max_unlock_points,
                          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.value.hdhive_max_unlock_points) = $event)),
                          label: "积分上限",
                          type: "number",
                          placeholder: "20",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_candidate_page_size,
                          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((config.value.hdhive_candidate_page_size) = $event)),
                          label: "候选页大小",
                          type: "number",
                          placeholder: "10",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_timeout,
                          "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((config.value.hdhive_timeout) = $event)),
                          label: "超时(秒)",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
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
                          modelValue: config.value.hdhive_base_url,
                          "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((config.value.hdhive_base_url) = $event)),
                          label: "影巢地址",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
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
                          modelValue: config.value.hdhive_default_path,
                          "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((config.value.hdhive_default_path) = $event)),
                          label: "影巢默认转存目录",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
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
                          modelValue: config.value.hdhive_api_key,
                          "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((config.value.hdhive_api_key) = $event)),
                          type: showHdhiveApiKey.value ? 'text' : 'password',
                          label: "影巢 API Key",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showHdhiveApiKey.value ? 'mdi-eye-off' : 'mdi-eye',
                              class: "me-2",
                              size: "small",
                              onClick: _cache[22] || (_cache[22] = $event => (showHdhiveApiKey.value = !showHdhiveApiKey.value))
                            }, null, 8, ["icon"]),
                            _createVNode(_component_VIcon, {
                              icon: "mdi-content-copy",
                              size: "small",
                              disabled: !config.value.hdhive_api_key,
                              onClick: _cache[23] || (_cache[23] = $event => (copyText(config.value.hdhive_api_key, '影巢 API Key')))
                            }, null, 8, ["disabled"])
                          ]),
                          _: 1
                        }, 8, ["modelValue", "type"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_openapi_user_token,
                          "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((config.value.hdhive_openapi_user_token) = $event)),
                          type: showHdhiveAccessToken.value ? 'text' : 'password',
                          label: "OpenAPI Access Token",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showHdhiveAccessToken.value ? 'mdi-eye-off' : 'mdi-eye',
                              class: "me-2",
                              size: "small",
                              onClick: _cache[25] || (_cache[25] = $event => (showHdhiveAccessToken.value = !showHdhiveAccessToken.value))
                            }, null, 8, ["icon"]),
                            _createVNode(_component_VIcon, {
                              icon: "mdi-content-copy",
                              size: "small",
                              disabled: !config.value.hdhive_openapi_user_token,
                              onClick: _cache[26] || (_cache[26] = $event => (copyText(config.value.hdhive_openapi_user_token, '影巢 Access Token')))
                            }, null, 8, ["disabled"])
                          ]),
                          _: 1
                        }, 8, ["modelValue", "type"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_openapi_refresh_token,
                          "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((config.value.hdhive_openapi_refresh_token) = $event)),
                          type: showHdhiveRefreshToken.value ? 'text' : 'password',
                          label: "OpenAPI Refresh Token（可选）",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showHdhiveRefreshToken.value ? 'mdi-eye-off' : 'mdi-eye',
                              class: "me-2",
                              size: "small",
                              onClick: _cache[28] || (_cache[28] = $event => (showHdhiveRefreshToken.value = !showHdhiveRefreshToken.value))
                            }, null, 8, ["icon"]),
                            _createVNode(_component_VIcon, {
                              icon: "mdi-content-copy",
                              size: "small",
                              disabled: !config.value.hdhive_openapi_refresh_token,
                              onClick: _cache[29] || (_cache[29] = $event => (copyText(config.value.hdhive_openapi_refresh_token, '影巢 Refresh Token')))
                            }, null, 8, ["disabled"])
                          ]),
                          _: 1
                        }, 8, ["modelValue", "type"])
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
        }),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-calendar-check-outline",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: enableChip(config.value.hdhive_checkin_enabled).color,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(enableChip(config.value.hdhive_checkin_enabled).text), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[67] || (_cache[67] = [
                    _createTextVNode("影巢签到", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[68] || (_cache[68] = [
                    _createTextVNode("OpenAPI 优先，网页 Cookie 兜底，按 Cron 自动签到", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.hdhive_checkin_enabled,
                          "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((config.value.hdhive_checkin_enabled) = $event)),
                          label: "启用签到",
                          color: "success",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.hdhive_checkin_gambler_mode,
                          "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((config.value.hdhive_checkin_gambler_mode) = $event)),
                          label: "默认赌狗签到",
                          color: "warning",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.hdhive_checkin_once,
                          "onUpdate:modelValue": _cache[33] || (_cache[33] = $event => ((config.value.hdhive_checkin_once) = $event)),
                          label: "保存后立即运行",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.hdhive_checkin_auto_login,
                          "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((config.value.hdhive_checkin_auto_login) = $event)),
                          label: "自动刷新 Cookie",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "4",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_checkin_cron,
                          "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((config.value.hdhive_checkin_cron) = $event)),
                          label: "签到 Cron",
                          placeholder: "0 8 * * *",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "4",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_checkin_username,
                          "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((config.value.hdhive_checkin_username) = $event)),
                          label: "影巢用户名/邮箱",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "4",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_checkin_password,
                          "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((config.value.hdhive_checkin_password) = $event)),
                          type: showHdhivePassword.value ? 'text' : 'password',
                          label: "影巢密码",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showHdhivePassword.value ? 'mdi-eye-off' : 'mdi-eye',
                              size: "small",
                              onClick: _cache[37] || (_cache[37] = $event => (showHdhivePassword.value = !showHdhivePassword.value))
                            }, null, 8, ["icon"])
                          ]),
                          _: 1
                        }, 8, ["modelValue", "type"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.hdhive_checkin_cookie,
                          "onUpdate:modelValue": _cache[41] || (_cache[41] = $event => ((config.value.hdhive_checkin_cookie) = $event)),
                          type: showHdhiveCookie.value ? 'text' : 'password',
                          label: "影巢网页 Cookie（非 Premium 兜底）",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showHdhiveCookie.value ? 'mdi-eye-off' : 'mdi-eye',
                              class: "me-2",
                              size: "small",
                              onClick: _cache[39] || (_cache[39] = $event => (showHdhiveCookie.value = !showHdhiveCookie.value))
                            }, null, 8, ["icon"]),
                            _createVNode(_component_VIcon, {
                              icon: "mdi-content-copy",
                              size: "small",
                              disabled: !config.value.hdhive_checkin_cookie,
                              onClick: _cache[40] || (_cache[40] = $event => (copyText(config.value.hdhive_checkin_cookie, '影巢 Cookie')))
                            }, null, 8, ["disabled"])
                          ]),
                          _: 1
                        }, 8, ["modelValue", "type"])
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
        }),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-magnify-scan",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: enableChip(config.value.pansou_enabled).color,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(enableChip(config.value.pansou_enabled).text), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[69] || (_cache[69] = [
                    _createTextVNode("盘搜", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[70] || (_cache[70] = [
                    _createTextVNode("聚合公开网盘分享，地址需容器视角可访问", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.pansou_enabled,
                          "onUpdate:modelValue": _cache[42] || (_cache[42] = $event => ((config.value.pansou_enabled) = $event)),
                          label: "启用盘搜",
                          color: "success",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "8",
                      sm: "6",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.pansou_base_url,
                          "onUpdate:modelValue": _cache[43] || (_cache[43] = $event => ((config.value.pansou_base_url) = $event)),
                          label: "盘搜 API 地址",
                          placeholder: "http://host.docker.internal:805",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "4",
                      sm: "3",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.pansou_timeout,
                          "onUpdate:modelValue": _cache[44] || (_cache[44] = $event => ((config.value.pansou_timeout) = $event)),
                          label: "超时(秒)",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, null, 8, ["modelValue"])
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
        }),
        _createVNode(_component_VCard, {
          variant: "outlined",
          class: "aro-card mb-3 rounded-lg"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, { class: "aro-card-head" }, {
              prepend: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-message-badge-outline",
                  color: "primary"
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_VChip, {
                  color: enableChip(config.value.feishu_enabled).color,
                  size: "small",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(enableChip(config.value.feishu_enabled).text), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
                  default: _withCtx(() => [...(_cache[71] || (_cache[71] = [
                    _createTextVNode("飞书入口", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-caption" }, {
                  default: _withCtx(() => [...(_cache[72] || (_cache[72] = [
                    _createTextVNode("内置飞书机器人入口与会话白名单", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "pt-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VRow, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      sm: "4",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.feishu_enabled,
                          "onUpdate:modelValue": _cache[45] || (_cache[45] = $event => ((config.value.feishu_enabled) = $event)),
                          label: "启用飞书入口",
                          color: "success",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "4",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.feishu_allow_all,
                          "onUpdate:modelValue": _cache[46] || (_cache[46] = $event => ((config.value.feishu_allow_all) = $event)),
                          label: "允许所有会话",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      sm: "4",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.feishu_reply_enabled,
                          "onUpdate:modelValue": _cache[47] || (_cache[47] = $event => ((config.value.feishu_reply_enabled) = $event)),
                          label: "发送飞书回复",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
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
                          modelValue: config.value.feishu_app_id,
                          "onUpdate:modelValue": _cache[48] || (_cache[48] = $event => ((config.value.feishu_app_id) = $event)),
                          label: "飞书 App ID",
                          placeholder: "cli_xxxxxxxxx",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
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
                          type: showFeishuSecret.value ? 'text' : 'password',
                          modelValue: config.value.feishu_app_secret,
                          "onUpdate:modelValue": _cache[50] || (_cache[50] = $event => ((config.value.feishu_app_secret) = $event)),
                          label: "飞书 App Secret",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": "auto"
                        }, {
                          "append-inner": _withCtx(() => [
                            _createVNode(_component_VIcon, {
                              icon: showFeishuSecret.value ? 'mdi-eye-off' : 'mdi-eye',
                              size: "small",
                              onClick: _cache[49] || (_cache[49] = $event => (showFeishuSecret.value = !showFeishuSecret.value))
                            }, null, 8, ["icon"])
                          ]),
                          _: 1
                        }, 8, ["type", "modelValue"])
                      ]),
                      _: 1
                    }),
                    (!config.value.feishu_allow_all)
                      ? (_openBlock(), _createBlock(_component_VCol, {
                          key: 0,
                          cols: "12",
                          class: "py-0"
                        }, {
                          default: _withCtx(() => [...(_cache[73] || (_cache[73] = [
                            _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "未允许所有会话时，仅下列白名单中的群聊或用户可触发飞书命令。", -1)
                          ]))]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                    (!config.value.feishu_allow_all)
                      ? (_openBlock(), _createBlock(_component_VCol, {
                          key: 1,
                          cols: "12",
                          md: "6"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VTextarea, {
                              modelValue: config.value.feishu_allowed_chat_ids,
                              "onUpdate:modelValue": _cache[51] || (_cache[51] = $event => ((config.value.feishu_allowed_chat_ids) = $event)),
                              label: "允许的群聊 Chat ID",
                              rows: "2",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto"
                            }, null, 8, ["modelValue"])
                          ]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                    (!config.value.feishu_allow_all)
                      ? (_openBlock(), _createBlock(_component_VCol, {
                          key: 2,
                          cols: "12",
                          md: "6"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VTextarea, {
                              modelValue: config.value.feishu_allowed_user_ids,
                              "onUpdate:modelValue": _cache[52] || (_cache[52] = $event => ((config.value.feishu_allowed_user_ids) = $event)),
                              label: "允许的用户 Open ID",
                              rows: "2",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto"
                            }, null, 8, ["modelValue"])
                          ]),
                          _: 1
                        }))
                      : _createCommentVNode("", true)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ])
    ]),
    _createVNode(_component_VDialog, {
      modelValue: qr.show,
      "onUpdate:modelValue": [
        _cache[53] || (_cache[53] = $event => ((qr.show) = $event)),
        _cache[54] || (_cache[54] = value => !value && closeQrDialog())
      ],
      "max-width": "450"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5" }, {
              default: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-qrcode",
                  color: "primary",
                  size: "small",
                  class: "me-2"
                }),
                _cache[74] || (_cache[74] = _createTextVNode(" 115网盘扫码登录 ", -1))
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "text-center py-4" }, {
              default: _withCtx(() => [
                (qr.error)
                  ? (_openBlock(), _createBlock(_component_VAlert, {
                      key: 0,
                      type: "error",
                      density: "compact",
                      variant: "tonal",
                      closable: "",
                      class: "mb-3 mx-3"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(qr.error), 1)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true),
                (qr.loading)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
                      _createVNode(_component_VProgressCircular, {
                        indeterminate: "",
                        color: "primary",
                        class: "mb-3"
                      }),
                      _cache[75] || (_cache[75] = _createElementVNode("div", null, "正在获取二维码...", -1))
                    ]))
                  : (qr.qrcode)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_6, [
                        _cache[77] || (_cache[77] = _createElementVNode("div", { class: "mb-2 font-weight-medium" }, "请选择扫码方式", -1)),
                        _createVNode(_component_VChipGroup, {
                          "model-value": qr.clientType,
                          class: "mb-3",
                          mandatory: "",
                          "selected-class": "primary",
                          "onUpdate:modelValue": changeQrClientType
                        }, {
                          default: _withCtx(() => [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_unref(CLIENT_TYPES), (item) => {
                              return (_openBlock(), _createBlock(_component_VChip, {
                                key: item.value,
                                value: item.value,
                                variant: "outlined",
                                color: "primary",
                                size: "small"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode(_toDisplayString(item.label), 1)
                                ]),
                                _: 2
                              }, 1032, ["value"]))
                            }), 128))
                          ]),
                          _: 1
                        }, 8, ["model-value"]),
                        _createElementVNode("div", _hoisted_7, [
                          _createVNode(_component_VCard, {
                            flat: "",
                            class: "border pa-2 mb-2"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("img", {
                                src: qr.qrcode,
                                width: "220",
                                height: "220",
                                alt: "115 登录二维码"
                              }, null, 8, _hoisted_8)
                            ]),
                            _: 1
                          }),
                          _createElementVNode("div", _hoisted_9, _toDisplayString(qr.tips), 1),
                          _createElementVNode("div", _hoisted_10, _toDisplayString(qr.status), 1)
                        ]),
                        _createVNode(_component_VBtn, {
                          color: "primary",
                          variant: "tonal",
                          size: "small",
                          class: "mb-2",
                          "prepend-icon": "mdi-refresh",
                          disabled: qr.loading,
                          onClick: refreshQrCode
                        }, {
                          default: _withCtx(() => [...(_cache[76] || (_cache[76] = [
                            _createTextVNode(" 刷新二维码 ", -1)
                          ]))]),
                          _: 1
                        }, 8, ["disabled"])
                      ]))
                    : (_openBlock(), _createElementBlock("div", _hoisted_11, [
                        _createVNode(_component_VIcon, {
                          icon: "mdi-qrcode-off",
                          size: "64",
                          color: "grey",
                          class: "mb-3"
                        }),
                        _cache[78] || (_cache[78] = _createElementVNode("div", { class: "text-subtitle-1" }, "二维码获取失败", -1)),
                        _cache[79] || (_cache[79] = _createElementVNode("div", { class: "text-body-2 text-grey" }, "请点击刷新按钮重试", -1))
                      ]))
              ]),
              _: 1
            }),
            _createVNode(_component_VDivider),
            _createVNode(_component_VCardActions, { class: "px-3 py-2" }, {
              default: _withCtx(() => [
                _createVNode(_component_VBtn, {
                  color: "grey",
                  variant: "text",
                  size: "small",
                  "prepend-icon": "mdi-close",
                  onClick: closeQrDialog
                }, {
                  default: _withCtx(() => [...(_cache[80] || (_cache[80] = [
                    _createTextVNode("关闭", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "text",
                  size: "small",
                  "prepend-icon": "mdi-refresh",
                  disabled: qr.loading,
                  onClick: refreshQrCode
                }, {
                  default: _withCtx(() => [...(_cache[81] || (_cache[81] = [
                    _createTextVNode("刷新二维码", -1)
                  ]))]),
                  _: 1
                }, 8, ["disabled"])
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-eb2e8235"]]);

export { Config as default };
