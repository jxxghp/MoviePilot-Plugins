import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,createElementVNode:_createElementVNode,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "oidc-auth-admin pa-4" };
const _hoisted_2 = { class: "d-flex flex-wrap gap-3 mt-2" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'OidcAuth',
  },
},
  setup(__props) {

const props = __props;

const loading = ref(false);
const saving = ref(false);
const testing = ref(false);
const binding = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const status = ref({
  public: {},
  binding: {},
  config: null,
  is_superuser: false,
});
const config = ref({
  enabled: false,
  provider_name: 'OIDC 登录',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  redirect_uri: '',
  username_claim: 'preferred_username',
  email_claim: 'email',
  allow_auto_bind_by_username: false,
});
let bindPopupTimer = null;

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`);
const isAdmin = computed(() => Boolean(status.value.is_superuser));
const isBound = computed(() => Boolean(status.value.binding?.bound));

/** 从 API 响应中解出 data 字段。 */
function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data')) {
    return response.data
  }
  return response
}

/** 清理提示信息。 */
function clearMessages() {
  errorMessage.value = '';
  successMessage.value = '';
}

/** 从服务端加载插件状态、配置和绑定信息。 */
async function loadStatus() {
  loading.value = true;
  clearMessages();
  try {
    const response = await props.api.get(`${pluginBase.value}/status`);
    status.value = unwrap(response) || status.value;
    if (status.value.config) {
      config.value = { ...config.value, ...status.value.config };
    }
  } catch (error) {
    errorMessage.value = error?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

/** 保存管理员配置。 */
async function saveConfig() {
  saving.value = true;
  clearMessages();
  try {
    const response = await props.api.post(`${pluginBase.value}/config`, config.value);
    const data = unwrap(response) || {};
    if (data.config) {
      config.value = { ...config.value, ...data.config };
    }
    successMessage.value = '配置已保存';
    await loadStatus();
  } catch (error) {
    errorMessage.value = error?.message || '保存失败';
  } finally {
    saving.value = false;
  }
}

/** 测试 OIDC Provider 发现文档。 */
async function testConnection() {
  testing.value = true;
  clearMessages();
  try {
    const response = await props.api.post(`${pluginBase.value}/test`, config.value);
    if (response?.success) {
      successMessage.value = response.message || '连接正常';
    } else {
      errorMessage.value = response?.message || '连接失败';
    }
  } catch (error) {
    errorMessage.value = error?.message || '连接失败';
  } finally {
    testing.value = false;
  }
}

/** 清理绑定弹窗轮询。 */
function clearBindPopupTimer() {
  if (bindPopupTimer) {
    clearInterval(bindPopupTimer);
    bindPopupTimer = null;
  }
}

/** 处理绑定回调消息。 */
function handleBindMessage(event) {
  if (event.origin !== window.location.origin) return
  if (event.data?.type !== 'oidcauth_bind_callback') return
  window.removeEventListener('message', handleBindMessage);
  clearBindPopupTimer();
  binding.value = false;
  if (event.data.success) {
    successMessage.value = 'OIDC 账号已绑定';
    loadStatus();
    return
  }
  errorMessage.value = event.data?.message || '绑定失败';
}

/** 发起账号绑定。 */
async function bindAccount() {
  binding.value = true;
  clearMessages();
  try {
    const response = await props.api.post(`${pluginBase.value}/bind/start`, {});
    const authorizeUrl = response?.data?.authorize_url;
    if (!response?.success || !authorizeUrl) {
      throw new Error(response?.message || '无法发起绑定')
    }
    window.addEventListener('message', handleBindMessage);
    const popup = window.open(authorizeUrl, 'moviepilot_oidc_bind', 'width=600,height=720,left=200,top=80');
    if (!popup) {
      window.removeEventListener('message', handleBindMessage);
      throw new Error('浏览器阻止了认证弹窗')
    }
    bindPopupTimer = setInterval(() => {
      if (!popup.closed) return
      clearBindPopupTimer();
      window.removeEventListener('message', handleBindMessage);
      if (binding.value) {
        binding.value = false;
        loadStatus();
      }
    }, 500);
  } catch (error) {
    binding.value = false;
    errorMessage.value = error?.message || '绑定失败';
  }
}

/** 解绑当前账号。 */
async function unbindAccount() {
  binding.value = true;
  clearMessages();
  try {
    const response = await props.api.post(`${pluginBase.value}/unbind`, {});
    if (response?.success) {
      successMessage.value = 'OIDC 账号已解绑';
      await loadStatus();
    } else {
      errorMessage.value = response?.message || '解绑失败';
    }
  } catch (error) {
    errorMessage.value = error?.message || '解绑失败';
  } finally {
    binding.value = false;
  }
}

/** 组件挂载时加载状态。 */
onMounted(loadStatus);

/** 组件卸载时清理绑定监听器。 */
onUnmounted(() => {
  clearBindPopupTimer();
  window.removeEventListener('message', handleBindMessage);
});

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardSubtitle = _resolveComponent("VCardSubtitle");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VRow = _resolveComponent("VRow");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (errorMessage.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(errorMessage.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (successMessage.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "success",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(successMessage.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_VCard, {
      loading: loading.value,
      class: "mb-4"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardItem, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, null, {
              default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                _createTextVNode("OIDC 账号绑定", -1)
              ]))]),
              _: 1
            }),
            (isBound.value)
              ? (_openBlock(), _createBlock(_component_VCardSubtitle, { key: 0 }, {
                  default: _withCtx(() => [
                    _createTextVNode("已绑定 " + _toDisplayString(status.value.binding?.masked_sub), 1)
                  ]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_VCardSubtitle, { key: 1 }, {
                  default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                    _createTextVNode("当前账号尚未绑定 OIDC", -1)
                  ]))]),
                  _: 1
                }))
          ]),
          _: 1
        }),
        _createVNode(_component_VCardText, null, {
          default: _withCtx(() => [
            (!isBound.value)
              ? (_openBlock(), _createBlock(_component_VBtn, {
                  key: 0,
                  color: "primary",
                  "prepend-icon": "mdi-openid",
                  loading: binding.value,
                  onClick: bindAccount
                }, {
                  default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                    _createTextVNode(" 绑定 OIDC 账号 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"]))
              : (_openBlock(), _createBlock(_component_VBtn, {
                  key: 1,
                  color: "error",
                  variant: "tonal",
                  "prepend-icon": "mdi-link-off",
                  loading: binding.value,
                  onClick: unbindAccount
                }, {
                  default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                    _createTextVNode(" 解绑 OIDC 账号 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"]))
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["loading"]),
    (isAdmin.value)
      ? (_openBlock(), _createBlock(_component_VCard, { key: 2 }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, null, {
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, null, {
                  default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                    _createTextVNode("OIDC Provider 配置", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, null, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(status.value.public?.redirect_uri), 1)
                  ]),
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
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.enabled,
                          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.value.enabled) = $event)),
                          label: "启用 OIDC 登录",
                          color: "primary"
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
                          modelValue: config.value.provider_name,
                          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.value.provider_name) = $event)),
                          label: "入口名称",
                          "prepend-inner-icon": "mdi-openid"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: config.value.issuer,
                          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.value.issuer) = $event)),
                          label: "Issuer",
                          placeholder: "https://idp.example.com",
                          "prepend-inner-icon": "mdi-web"
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
                          modelValue: config.value.client_id,
                          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.value.client_id) = $event)),
                          label: "Client ID",
                          "prepend-inner-icon": "mdi-identifier"
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
                          modelValue: config.value.client_secret,
                          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.value.client_secret) = $event)),
                          label: "Client Secret",
                          type: "password",
                          "prepend-inner-icon": "mdi-key"
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
                          modelValue: config.value.scopes,
                          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.value.scopes) = $event)),
                          label: "Scopes",
                          placeholder: "openid profile email",
                          "prepend-inner-icon": "mdi-format-list-checks"
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
                          modelValue: config.value.redirect_uri,
                          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.value.redirect_uri) = $event)),
                          label: "回调地址覆盖",
                          placeholder: "留空自动生成",
                          "prepend-inner-icon": "mdi-call-made"
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
                          modelValue: config.value.username_claim,
                          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.value.username_claim) = $event)),
                          label: "用户名 Claim",
                          "prepend-inner-icon": "mdi-account"
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
                          modelValue: config.value.email_claim,
                          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.value.email_claim) = $event)),
                          label: "邮箱 Claim",
                          "prepend-inner-icon": "mdi-email"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSwitch, {
                          modelValue: config.value.allow_auto_bind_by_username,
                          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.value.allow_auto_bind_by_username) = $event)),
                          label: "允许按用户名 Claim 自动绑定已有用户",
                          color: "primary"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_2, [
                  _createVNode(_component_VBtn, {
                    color: "primary",
                    "prepend-icon": "mdi-content-save",
                    loading: saving.value,
                    onClick: saveConfig
                  }, {
                    default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                      _createTextVNode("保存", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading"]),
                  _createVNode(_component_VBtn, {
                    color: "info",
                    variant: "tonal",
                    "prepend-icon": "mdi-connection",
                    loading: testing.value,
                    onClick: testConnection
                  }, {
                    default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                      _createTextVNode("测试连接", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading"])
                ])
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true)
  ]))
}
}

};

export { _sfc_main as default };
