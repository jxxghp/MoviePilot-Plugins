import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "oidc-auth-config pa-4" };
const _hoisted_2 = { class: "rounded-lg border pa-4 mt-4" };
const _hoisted_3 = { class: "d-flex align-center gap-2 mb-3" };
const _hoisted_4 = { class: "d-flex gap-3 mb-2" };
const _hoisted_5 = { class: "text-body-2" };
const _hoisted_6 = {
  key: 1,
  class: "text-medium-emphasis"
};
const _hoisted_7 = { class: "d-flex flex-wrap gap-3 mt-4" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'ConfigPage',
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
  emits: ['close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const loading = ref(false);
const saving = ref(false);
const testing = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const status = ref({
  public: {},
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

const copied = ref(false);
let copyTimer = null;

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`);

const displayRedirectUri = computed(() => {
  const raw = status.value.public?.redirect_uri || '';
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  return `${window.location.origin}${raw}`
});

async function copyRedirectUri() {
  try {
    await navigator.clipboard.writeText(displayRedirectUri.value);
    copied.value = true;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { copied.value = false; }, 2000);
  } catch { /* 忽略 */ }
}

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data')) {
    return response.data
  }
  return response
}

function clearMessages() {
  errorMessage.value = '';
  successMessage.value = '';
}

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

async function saveConfig() {
  saving.value = true;
  clearMessages();
  try {
    const response = await props.api.post(`${pluginBase.value}/config`, config.value);
    const data = unwrap(response) || {};
    if (data.config) {
      config.value = { ...config.value, ...data.config };
    }
    await loadStatus();
    successMessage.value = '配置已保存，即将刷新页面...';
    setTimeout(() => window.location.reload(), 1000);
  } catch (error) {
    errorMessage.value = error?.message || '保存失败';
  } finally {
    saving.value = false;
  }
}

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

onMounted(loadStatus);

onUnmounted(() => {
  clearTimeout(copyTimer);
});

return (_ctx, _cache) => {
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VCard, { loading: loading.value }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardItem, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, null, {
              default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                _createTextVNode("OIDC Provider 配置", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VCardText, null, {
          default: _withCtx(() => [
            _createVNode(_component_VSwitch, {
              modelValue: config.value.enabled,
              "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.value.enabled) = $event)),
              label: "启用 OIDC 登录",
              color: "primary",
              class: "mb-2"
            }, null, 8, ["modelValue"]),
            (config.value.enabled)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createVNode(_component_VRow, null, {
                    default: _withCtx(() => [
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
                    _createElementVNode("div", _hoisted_3, [
                      _createVNode(_component_VIcon, {
                        size: "20",
                        color: "primary"
                      }, {
                        default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                          _createTextVNode("mdi-information-outline", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[12] || (_cache[12] = _createElementVNode("span", { class: "text-subtitle-2 font-weight-medium" }, "使用指南", -1))
                    ]),
                    _cache[17] || (_cache[17] = _createElementVNode("div", { class: "d-flex gap-3 mb-2" }, [
                      _createElementVNode("div", {
                        class: "text-medium-emphasis",
                        style: {"min-width":"16px"}
                      }, "1."),
                      _createElementVNode("div", { class: "text-body-2" }, "在您的 OIDC 提供商（如 Keycloak、Authentik、Okta 等）中创建一个客户端，协议类型选择 \"OAuth2/OpenID Provider\"，授权流程使用 \"Authorize Application\"。")
                    ], -1)),
                    _createElementVNode("div", _hoisted_4, [
                      _cache[16] || (_cache[16] = _createElementVNode("div", {
                        class: "text-medium-emphasis",
                        style: {"min-width":"16px"}
                      }, "2.", -1)),
                      _createElementVNode("div", _hoisted_5, [
                        _cache[15] || (_cache[15] = _createTextVNode(" 将回调地址设置为： ", -1)),
                        (displayRedirectUri.value)
                          ? (_openBlock(), _createBlock(_component_VChip, {
                              key: 0,
                              color: "info",
                              variant: "tonal",
                              size: "small",
                              class: "cursor-pointer ml-1",
                              onClick: copyRedirectUri
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(displayRedirectUri.value) + " ", 1),
                                (copied.value)
                                  ? (_openBlock(), _createBlock(_component_VIcon, {
                                      key: 0,
                                      end: "",
                                      size: "14",
                                      color: "success"
                                    }, {
                                      default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                                        _createTextVNode("mdi-check", -1)
                                      ]))]),
                                      _: 1
                                    }))
                                  : (_openBlock(), _createBlock(_component_VIcon, {
                                      key: 1,
                                      end: "",
                                      size: "14"
                                    }, {
                                      default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                                        _createTextVNode("mdi-content-copy", -1)
                                      ]))]),
                                      _: 1
                                    }))
                              ]),
                              _: 1
                            }))
                          : (_openBlock(), _createElementBlock("span", _hoisted_6, "加载中..."))
                      ])
                    ]),
                    _cache[18] || (_cache[18] = _createElementVNode("div", { class: "d-flex gap-3 mb-2" }, [
                      _createElementVNode("div", {
                        class: "text-medium-emphasis",
                        style: {"min-width":"16px"}
                      }, "3."),
                      _createElementVNode("div", { class: "text-body-2" }, [
                        _createTextVNode(" 填写签发者 URL、客户端 ID 和客户端密钥，保存设置。 "),
                        _createElementVNode("div", { class: "text-medium-emphasis text-caption mt-1" }, [
                          _createTextVNode("如果 IdP 与 MoviePilot 不在同一网络、需要指定不同的回调地址，可在「回调地址覆盖」中手动填写完整地址（如 "),
                          _createElementVNode("code", { class: "text-caption" }, "https://another-domain.com/api/v1/plugin/OidcAuth/callback"),
                          _createTextVNode("），正常情况下留空即可。")
                        ])
                      ])
                    ], -1)),
                    _cache[19] || (_cache[19] = _createElementVNode("div", { class: "d-flex gap-3 mb-2" }, [
                      _createElementVNode("div", {
                        class: "text-medium-emphasis",
                        style: {"min-width":"16px"}
                      }, "4."),
                      _createElementVNode("div", { class: "text-body-2" }, "保存后登录页面将显示 OIDC 登录按钮。")
                    ], -1)),
                    _cache[20] || (_cache[20] = _createElementVNode("div", { class: "d-flex gap-3" }, [
                      _createElementVNode("div", {
                        class: "text-medium-emphasis",
                        style: {"min-width":"16px"}
                      }, "5."),
                      _createElementVNode("div", { class: "text-body-2" }, "已登录用户可在左侧菜单「OIDC 认证」中绑定/解绑 OIDC 账号。")
                    ], -1))
                  ])
                ], 64))
              : _createCommentVNode("", true),
            _createElementVNode("div", _hoisted_7, [
              _createVNode(_component_VBtn, {
                color: "primary",
                "prepend-icon": "mdi-content-save",
                loading: saving.value,
                onClick: saveConfig
              }, {
                default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                  _createTextVNode("保存", -1)
                ]))]),
                _: 1
              }, 8, ["loading"]),
              (config.value.enabled)
                ? (_openBlock(), _createBlock(_component_VBtn, {
                    key: 0,
                    color: "info",
                    variant: "tonal",
                    "prepend-icon": "mdi-connection",
                    loading: testing.value,
                    onClick: testConnection
                  }, {
                    default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                      _createTextVNode("测试连接", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading"]))
                : _createCommentVNode("", true)
            ]),
            (errorMessage.value)
              ? (_openBlock(), _createBlock(_component_VAlert, {
                  key: 1,
                  type: "error",
                  variant: "tonal",
                  class: "mt-4"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(errorMessage.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (successMessage.value)
              ? (_openBlock(), _createBlock(_component_VAlert, {
                  key: 2,
                  type: "success",
                  variant: "tonal",
                  class: "mt-4"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(successMessage.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true)
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["loading"])
  ]))
}
}

};

export { _sfc_main as default };
