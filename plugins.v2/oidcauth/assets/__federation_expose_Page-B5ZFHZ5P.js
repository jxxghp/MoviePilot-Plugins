import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createTextVNode:_createTextVNode,toDisplayString:_toDisplayString,createCommentVNode:_createCommentVNode,createBlock:_createBlock} = await importShared('vue');


const _hoisted_1 = { class: "oidc-auth-page pa-4" };
const _hoisted_2 = {
  key: 0,
  class: "text-success"
};
const _hoisted_3 = {
  key: 1,
  class: "text-medium-emphasis"
};
const _hoisted_4 = { class: "d-flex flex-wrap gap-3 align-center" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
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
  emits: ['close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const loading = ref(false);
const binding = ref(false);
const bindErrorMessage = ref('');
const bindSuccessMessage = ref('');
const status = ref({ public: {}, binding: {} });

let bindPopupTimer = null;
let bindMessageReceived = false;
let bindPollingLock = false;

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`);
const isBound = computed(() => Boolean(status.value.binding?.bound));
const isAdmin = computed(() => status.value.is_superuser);

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data')) {
    return response.data
  }
  return response
}

async function loadStatus() {
  loading.value = true;
  try {
    const response = await props.api.get(`${pluginBase.value}/status`);
    status.value = unwrap(response) || status.value;
  } catch (error) {
    bindErrorMessage.value = error?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

function clearBindPopupTimer() {
  if (bindPopupTimer) {
    clearInterval(bindPopupTimer);
    bindPopupTimer = null;
  }
}

async function handleBindMessage(event) {
  if (event.origin !== window.location.origin) return
  if (event.data?.type !== 'oidcauth_bind_callback') return
  bindMessageReceived = true;
  window.removeEventListener('message', handleBindMessage);
  clearBindPopupTimer();
  binding.value = false;
  if (event.data.success) {
    await loadStatus();
    bindSuccessMessage.value = 'OIDC 账号已绑定';
    bindErrorMessage.value = '';
  } else {
    bindErrorMessage.value = event.data?.message || '绑定失败';
  }
}

async function bindAccount() {
  binding.value = true;
  bindErrorMessage.value = '';
  bindSuccessMessage.value = '';
  bindMessageReceived = false;
  bindPollingLock = false;
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
    bindPopupTimer = setInterval(async () => {
      // 防止上一次轮询还未完成
      if (bindPollingLock) return
      bindPollingLock = true;
      try {
        // 弹窗未关闭时，偷偷检查绑定状态（PostMessage 可能因 opener 丢失而失效）
        if (!popup.closed && !bindMessageReceived) {
          await loadStatus();
          if (isBound.value) {
            // 绑定已生效，关闭弹窗并标记成功
            bindMessageReceived = true;
            clearBindPopupTimer();
            window.removeEventListener('message', handleBindMessage);
            binding.value = false;
            bindSuccessMessage.value = 'OIDC 账号已绑定';
            bindErrorMessage.value = '';
            try { popup.close(); } catch (_) { /* 忽略跨域关闭错误 */ }
            return
          }
          return
        }
        if (!popup.closed) return
        // 弹窗已关闭
        clearBindPopupTimer();
        window.removeEventListener('message', handleBindMessage);
        if (!binding.value) return
        binding.value = false;
        if (bindMessageReceived) return
        // postMessage 丢失，重试轮询状态（最多 6 次，每次间隔 1.5 秒）
        for (let attempt = 0; attempt < 6; attempt++) {
          await loadStatus();
          if (isBound.value) {
            bindSuccessMessage.value = 'OIDC 账号已绑定';
            bindErrorMessage.value = '';
            return
          }
          if (attempt < 5) {
            await new Promise(r => setTimeout(r, 1500));
          }
        }
        bindErrorMessage.value = '绑定失败：未检测到绑定状态，请重试';
      } finally {
        bindPollingLock = false;
      }
    }, 1000);
  } catch (error) {
    binding.value = false;
    bindErrorMessage.value = error?.message || '绑定失败';
  }
}

async function unbindAccount() {
  binding.value = true;
  bindErrorMessage.value = '';
  bindSuccessMessage.value = '';
  try {
    const response = await props.api.post(`${pluginBase.value}/unbind`, {});
    if (response?.success) {
      await loadStatus();
      bindSuccessMessage.value = 'OIDC 账号已解绑';
      bindErrorMessage.value = '';
    } else {
      bindErrorMessage.value = response?.message || '解绑失败';
    }
  } catch (error) {
    bindErrorMessage.value = error?.message || '解绑失败';
  } finally {
    binding.value = false;
  }
}

onMounted(loadStatus);

onUnmounted(() => {
  clearBindPopupTimer();
  window.removeEventListener('message', handleBindMessage);
});

return (_ctx, _cache) => {
  const _component_VAvatar = _resolveComponent("VAvatar");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VCardSubtitle = _resolveComponent("VCardSubtitle");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (status.value.public?.enabled)
      ? (_openBlock(), _createBlock(_component_VCard, {
          key: 0,
          loading: loading.value,
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, null, {
              prepend: _withCtx(() => [
                _createVNode(_component_VAvatar, {
                  color: "primary",
                  size: "40"
                }, {
                  default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
                    _createElementVNode("svg", {
                      viewBox: "0 0 1024 1024",
                      width: "24",
                      height: "24",
                      fill: "white",
                      xmlns: "http://www.w3.org/2000/svg"
                    }, [
                      _createElementVNode("path", { d: "M468.064 866.08v91.616c-81.408-7.168-155.328-25.376-221.792-54.656-66.432-29.28-118.752-66.496-156.96-111.68C51.104 746.176 32 697.536 32 645.408c0-50.016 17.952-97.056 53.856-141.184 35.904-44.096 84.992-80.8 147.328-110.08s132.224-48.576 209.728-57.856v92.128c-77.504 13.568-141.152 40.352-190.976 80.352-49.824 40-74.72 85.536-74.72 136.64 0 54.272 27.584 101.952 82.752 143.04 55.168 41.056 124.544 66.944 208.096 77.632zM992 587.008l-19.808-208.928-75.008 42.304c-72.864-44.288-158.752-72.32-257.696-84.096v92.128c57.504 10.368 107.488 28.032 150.016 53.056l-78.752 44.48L992 587.008z" }),
                      _createElementVNode("path", { d: "M613.792 889.152l-145.728 68.576V137.536l145.728-71.264v822.88z" })
                    ], -1)
                  ]))]),
                  _: 1
                })
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, null, {
                  default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
                    _createTextVNode("OIDC 账号绑定", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, null, {
                  default: _withCtx(() => [
                    (isBound.value)
                      ? (_openBlock(), _createElementBlock("span", _hoisted_2, [
                          _createVNode(_component_VIcon, {
                            size: "14",
                            color: "success",
                            class: "mr-1"
                          }, {
                            default: _withCtx(() => [...(_cache[3] || (_cache[3] = [
                              _createTextVNode("mdi-check-circle", -1)
                            ]))]),
                            _: 1
                          }),
                          _createTextVNode(" 已绑定 " + _toDisplayString(status.value.binding?.sub || status.value.binding?.masked_sub), 1)
                        ]))
                      : (_openBlock(), _createElementBlock("span", _hoisted_3, "当前账号尚未绑定 OIDC"))
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_4, [
                  (!isBound.value)
                    ? (_openBlock(), _createBlock(_component_VBtn, {
                        key: 0,
                        color: "primary",
                        loading: binding.value,
                        onClick: bindAccount
                      }, {
                        prepend: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                          _createElementVNode("svg", {
                            viewBox: "0 0 1024 1024",
                            width: "20",
                            height: "20",
                            fill: "currentColor",
                            xmlns: "http://www.w3.org/2000/svg"
                          }, [
                            _createElementVNode("path", { d: "M468.064 866.08v91.616c-81.408-7.168-155.328-25.376-221.792-54.656-66.432-29.28-118.752-66.496-156.96-111.68C51.104 746.176 32 697.536 32 645.408c0-50.016 17.952-97.056 53.856-141.184 35.904-44.096 84.992-80.8 147.328-110.08s132.224-48.576 209.728-57.856v92.128c-77.504 13.568-141.152 40.352-190.976 80.352-49.824 40-74.72 85.536-74.72 136.64 0 54.272 27.584 101.952 82.752 143.04 55.168 41.056 124.544 66.944 208.096 77.632zM992 587.008l-19.808-208.928-75.008 42.304c-72.864-44.288-158.752-72.32-257.696-84.096v92.128c57.504 10.368 107.488 28.032 150.016 53.056l-78.752 44.48L992 587.008z" }),
                            _createElementVNode("path", { d: "M613.792 889.152l-145.728 68.576V137.536l145.728-71.264v822.88z" })
                          ], -1)
                        ]))]),
                        default: _withCtx(() => [
                          _cache[5] || (_cache[5] = _createTextVNode(" 绑定 OIDC 账号 ", -1))
                        ]),
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
                        default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                          _createTextVNode(" 解绑 OIDC 账号 ", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading"])),
                  (isAdmin.value)
                    ? (_openBlock(), _createBlock(_component_VBtn, {
                        key: 2,
                        color: "primary",
                        variant: "tonal",
                        "prepend-icon": "mdi-cog",
                        onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
                      }, {
                        default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                          _createTextVNode(" 配置 ", -1)
                        ]))]),
                        _: 1
                      }))
                    : _createCommentVNode("", true)
                ]),
                (bindErrorMessage.value)
                  ? (_openBlock(), _createBlock(_component_VAlert, {
                      key: 0,
                      type: "error",
                      variant: "tonal",
                      class: "mt-3"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(bindErrorMessage.value), 1)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true),
                (bindSuccessMessage.value)
                  ? (_openBlock(), _createBlock(_component_VAlert, {
                      key: 1,
                      type: "success",
                      variant: "tonal",
                      class: "mt-3"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(bindSuccessMessage.value), 1)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["loading"]))
      : (_openBlock(), _createBlock(_component_VCard, {
          key: 1,
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardItem, null, {
              prepend: _withCtx(() => [
                _createVNode(_component_VAvatar, {
                  color: "grey-lighten-2",
                  size: "40"
                }, {
                  default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                    _createElementVNode("svg", {
                      viewBox: "0 0 1024 1024",
                      width: "24",
                      height: "24",
                      fill: "#9E9E9E",
                      xmlns: "http://www.w3.org/2000/svg"
                    }, [
                      _createElementVNode("path", { d: "M468.064 866.08v91.616c-81.408-7.168-155.328-25.376-221.792-54.656-66.432-29.28-118.752-66.496-156.96-111.68C51.104 746.176 32 697.536 32 645.408c0-50.016 17.952-97.056 53.856-141.184 35.904-44.096 84.992-80.8 147.328-110.08s132.224-48.576 209.728-57.856v92.128c-77.504 13.568-141.152 40.352-190.976 80.352-49.824 40-74.72 85.536-74.72 136.64 0 54.272 27.584 101.952 82.752 143.04 55.168 41.056 124.544 66.944 208.096 77.632zM992 587.008l-19.808-208.928-75.008 42.304c-72.864-44.288-158.752-72.32-257.696-84.096v92.128c57.504 10.368 107.488 28.032 150.016 53.056l-78.752 44.48L992 587.008z" }),
                      _createElementVNode("path", { d: "M613.792 889.152l-145.728 68.576V137.536l145.728-71.264v822.88z" })
                    ], -1)
                  ]))]),
                  _: 1
                })
              ]),
              default: _withCtx(() => [
                _createVNode(_component_VCardTitle, null, {
                  default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                    _createTextVNode("OIDC 认证", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VCardSubtitle, { class: "text-medium-emphasis" }, {
                  default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                    _createTextVNode("OIDC 认证尚未启用", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                _createElementVNode("p", { class: "text-body-2 text-medium-emphasis" }, "请联系管理员在插件设置中配置 OIDC Provider。", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }))
  ]))
}
}

};

export { _sfc_main as default };
