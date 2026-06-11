import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {resolveComponent:_resolveComponent,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx} = await importShared('vue');


const _hoisted_1 = { class: "oidc-auth-page text-center" };
const _hoisted_2 = {
  key: 1,
  class: "text-body-2 text-medium-emphasis mb-2"
};
const _hoisted_3 = {
  key: 3,
  class: "text-body-2 text-medium-emphasis mb-2"
};

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');



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

const checking = ref(true);
const loading = ref(false);
const errorMessage = ref('');
let popupTimer = null;
let messageReceived = false;

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
  messageReceived = true;
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

/** 先自检 OIDC 是否已启用，再决定是否发起授权弹窗。 */
async function checkAndStart() {
  checking.value = true;
  errorMessage.value = '';
  try {
    const response = await props.api.get(`${pluginBase.value}/public/status`);
    const data = response?.data !== undefined ? response.data : response;
    if (!data?.enabled) {
      errorMessage.value = '管理员未启用OIDC认证，请联系管理员开启';
      emit('error', { message: errorMessage.value });
      return
    }
    startLogin();
  } catch {
    errorMessage.value = '无法连接到认证服务';
    emit('error', { message: errorMessage.value });
  } finally {
    checking.value = false;
  }
}

/** 发起 OIDC 登录授权弹窗。 */
function startLogin() {
  errorMessage.value = '';
  loading.value = true;
  messageReceived = false;
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
    if (loading.value && !messageReceived) {
      loading.value = false;
      errorMessage.value = '认证窗口已关闭';
      emit('error', { message: errorMessage.value });
    }
  }, 500);
}

/** 组件挂载后自检，通过后自动发起登录。 */
onMounted(() => {
  checkAndStart();
});

/** 组件卸载时清理监听器和定时器。 */
onUnmounted(() => {
  clearPopupTimer();
  window.removeEventListener('message', handleOidcMessage);
});

return (_ctx, _cache) => {
  const _component_VProgressCircular = _resolveComponent("VProgressCircular");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VBtn = _resolveComponent("VBtn");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (checking.value)
      ? (_openBlock(), _createBlock(_component_VProgressCircular, {
          key: 0,
          indeterminate: "",
          color: "primary",
          class: "mb-4"
        }))
      : _createCommentVNode("", true),
    (checking.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "正在检查认证服务状态..."))
      : (loading.value)
        ? (_openBlock(), _createBlock(_component_VProgressCircular, {
            key: 2,
            indeterminate: "",
            color: "primary",
            class: "mb-4"
          }))
        : (loading.value)
          ? (_openBlock(), _createElementBlock("div", _hoisted_3, "正在打开 " + _toDisplayString(providerName.value) + " 授权页面...", 1))
          : _createCommentVNode("", true),
    (!loading.value && !checking.value && errorMessage.value)
      ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 4,
          type: "error",
          variant: "tonal",
          class: "mb-2"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(errorMessage.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (!loading.value && !checking.value)
      ? (_openBlock(), _createBlock(_component_VBtn, {
          key: 5,
          block: "",
          color: "primary",
          onClick: checkAndStart
        }, {
          default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
            _createTextVNode("重试", -1)
          ]))]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (!loading.value && !checking.value)
      ? (_openBlock(), _createBlock(_component_VBtn, {
          key: 6,
          block: "",
          variant: "text",
          class: "mt-2",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
            _createTextVNode("取消", -1)
          ]))]),
          _: 1
        }))
      : _createCommentVNode("", true)
  ]))
}
}

};

export { _sfc_main as default };
