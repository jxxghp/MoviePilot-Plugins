import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "oidc-auth-page" };

const {computed,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'AuthPage',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  provider: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'OidcAuth',
  },
},
  emits: ['authenticated', 'error', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const loading = ref(false);
const errorMessage = ref('');
let popupTimer = null;

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`);
const providerName = computed(() => props.provider?.name || 'OIDC 登录');

/** 拼接 API 路径为可用于 window.open 的 URL。 */
function buildApiUrl(path) {
  const base = props.api?.defaults?.baseURL || '/api/v1/';
  const normalizedBase = base.endsWith('/') ? base : `${base}/`;
  const normalizedPath = String(path || '').replace(/^\/+/, '');
  return `${normalizedBase}${normalizedPath}`
}

/** 关闭弹窗轮询并清理状态。 */
function clearPopupTimer() {
  if (popupTimer) {
    clearInterval(popupTimer);
    popupTimer = null;
  }
}

/** 处理 OIDC 回调窗口发回的认证消息。 */
function handleOidcMessage(event) {
  if (event.origin !== window.location.origin) return
  if (event.data?.type !== 'oidcauth_callback') return
  window.removeEventListener('message', handleOidcMessage);
  clearPopupTimer();
  loading.value = false;
  if (event.data.success && event.data.data?.ticket) {
    emit('authenticated', { ticket: event.data.data.ticket });
    return
  }
  const message = event.data?.message || 'OIDC 认证失败';
  errorMessage.value = message;
  emit('error', { message });
}

/** 发起 OIDC 登录授权弹窗。 */
function startLogin() {
  errorMessage.value = '';
  loading.value = true;
  window.addEventListener('message', handleOidcMessage);
  const popup = window.open(
    buildApiUrl(`${pluginBase.value}/authorize`),
    'moviepilot_oidc_login',
    'width=600,height=720,left=200,top=80',
  );
  if (!popup) {
    loading.value = false;
    window.removeEventListener('message', handleOidcMessage);
    errorMessage.value = '浏览器阻止了认证弹窗';
    emit('error', { message: errorMessage.value });
    return
  }
  popupTimer = setInterval(() => {
    if (!popup.closed) return
    clearPopupTimer();
    window.removeEventListener('message', handleOidcMessage);
    if (loading.value) {
      loading.value = false;
      errorMessage.value = '认证窗口已关闭';
      emit('error', { message: errorMessage.value });
    }
  }, 500);
}

/** 组件卸载时清理监听器和定时器。 */
onUnmounted(() => {
  clearPopupTimer();
  window.removeEventListener('message', handleOidcMessage);
});

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VBtn = _resolveComponent("VBtn");

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
    _createVNode(_component_VBtn, {
      block: "",
      color: "primary",
      "prepend-icon": "mdi-openid",
      loading: loading.value,
      onClick: startLogin
    }, {
      default: _withCtx(() => [
        _createTextVNode(_toDisplayString(providerName.value), 1)
      ]),
      _: 1
    }, 8, ["loading"]),
    _createVNode(_component_VBtn, {
      block: "",
      variant: "text",
      class: "mt-2",
      onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
    }, {
      default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
        _createTextVNode("取消", -1)
      ]))]),
      _: 1
    })
  ]))
}
}

};

export { _sfc_main as default };
