import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,createCommentVNode:_createCommentVNode,createTextVNode:_createTextVNode,Fragment:_Fragment,normalizeClass:_normalizeClass,Transition:_Transition,withCtx:_withCtx,createVNode:_createVNode,createStaticVNode:_createStaticVNode} = await importShared('vue');


const _hoisted_1 = { class: "oidc-main" };
const _hoisted_2 = { class: "oidc-card oidc-right" };
const _hoisted_3 = { class: "oidc-right-top" };
const _hoisted_4 = { class: "oidc-right-title" };
const _hoisted_5 = {
  key: 0,
  class: "oidc-right-sub"
};
const _hoisted_6 = {
  key: 1,
  class: "oidc-bound-badge"
};
const _hoisted_7 = {
  key: 0,
  class: "oidc-disabled-banner"
};
const _hoisted_8 = { class: "oidc-right-body" };
const _hoisted_9 = {
  key: 0,
  class: "oidc-steps"
};
const _hoisted_10 = { class: "oidc-step-left" };
const _hoisted_11 = {
  key: 0,
  class: "oidc-step-check-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "3",
  "stroke-linecap": "round",
  "stroke-linejoin": "round"
};
const _hoisted_12 = {
  key: 1,
  class: "oidc-spinner"
};
const _hoisted_13 = {
  key: 2,
  class: "oidc-step-x-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "3",
  "stroke-linecap": "round",
  "stroke-linejoin": "round"
};
const _hoisted_14 = { class: "oidc-step-right" };
const _hoisted_15 = { class: "oidc-step-title" };
const _hoisted_16 = { class: "oidc-step-desc" };
const _hoisted_17 = { class: "oidc-step-left" };
const _hoisted_18 = {
  key: 0,
  class: "oidc-step-check-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "3",
  "stroke-linecap": "round",
  "stroke-linejoin": "round"
};
const _hoisted_19 = {
  key: 1,
  class: "oidc-spinner"
};
const _hoisted_20 = {
  key: 2,
  class: "oidc-step-x-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "3",
  "stroke-linecap": "round",
  "stroke-linejoin": "round"
};
const _hoisted_21 = { class: "oidc-step-right" };
const _hoisted_22 = { class: "oidc-step-title" };
const _hoisted_23 = { class: "oidc-step-desc" };
const _hoisted_24 = { class: "oidc-step-left" };
const _hoisted_25 = {
  key: 0,
  class: "oidc-step-check-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "3",
  "stroke-linecap": "round",
  "stroke-linejoin": "round"
};
const _hoisted_26 = {
  key: 1,
  class: "oidc-spinner"
};
const _hoisted_27 = {
  key: 2,
  class: "oidc-step-x-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "3",
  "stroke-linecap": "round",
  "stroke-linejoin": "round"
};
const _hoisted_28 = { class: "oidc-step-right" };
const _hoisted_29 = { class: "oidc-step-title" };
const _hoisted_30 = { class: "oidc-step-desc" };
const _hoisted_31 = { class: "oidc-info-rows" };
const _hoisted_32 = { class: "oidc-info-row" };
const _hoisted_33 = { class: "oidc-info-row-value" };
const _hoisted_34 = { class: "oidc-info-row" };
const _hoisted_35 = ["title"];
const _hoisted_36 = { class: "oidc-bound-desc" };
const _hoisted_37 = { class: "oidc-right-footer" };
const _hoisted_38 = ["disabled"];
const _hoisted_39 = { class: "oidc-unbind-actions" };
const _hoisted_40 = ["disabled"];
const _hoisted_41 = ["disabled"];
const _hoisted_42 = ["disabled"];
const _hoisted_43 = {
  key: 0,
  class: "oidc-alert oidc-alert-error"
};
const _hoisted_44 = {
  key: 0,
  class: "oidc-alert oidc-alert-success"
};
const _hoisted_45 = { class: "oidc-bottom" };
const _hoisted_46 = { class: "oidc-bottom-content" };
const _hoisted_47 = { class: "oidc-bottom-right" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');


const USER_ICON_SVG = `<svg viewBox="0 0 1025 1024" xmlns="http://www.w3.org/2000/svg"><path fill="white" d="M406.766493 519.191123C402.472299 519.191123 398.112041 518.365316 393.916945 516.581574 294.159525 474.432413 229.71359 377.185445 229.71359 268.872671 229.71359 120.623897 350.347396-0.00991 498.59617-0.00991 646.844945-0.00991 767.445719 120.623897 767.445719 268.872671 767.445719 373.849187 705.741461 469.873961 610.245203 513.509574 593.629977 521.073961 574.041848 513.806865 566.444428 497.224671 558.880041 480.609445 566.18017 461.021316 582.795396 453.456929 654.838751 420.523768 701.381203 348.050994 701.381203 268.872671 701.381203 157.025445 610.410364 66.054606 498.59617 66.054606 386.781977 66.054606 295.778106 157.025445 295.778106 268.872671 295.778106 350.594477 344.40159 423.92609 419.649074 455.736155 436.429461 462.83809 444.32417 482.228026 437.189203 499.041445 431.871009 511.626735 419.649074 519.191123 406.766493 519.191123"/><path fill="white" d="M673.71999 996.54689 673.686957 996.54689 103.087732 996.018374C67.148635 995.95231 34.413667 978.147923 15.519215 948.385858-2.714591 919.680826-4.960785 884.171148 9.44128 853.385084 59.485151 746.525729 190.623215 566.532955 506.708893 561.644181 831.614183 555.698374 949.803603 748.474632 991.325151 863.327794 1002.225796 893.486245 997.832506 925.989987 979.202312 952.547923 959.878441 980.096826 927.936248 996.54689 893.780893 996.54689L811.365409 996.54689C793.131603 996.54689 778.333151 981.781471 778.333151 963.514632 778.333151 945.247794 793.131603 930.482374 811.365409 930.482374L893.780893 930.482374C906.432248 930.482374 918.125667 924.536568 925.128506 914.62689 928.69599 909.50689 933.981151 899.002632 929.191474 885.756697 885.787086 765.750503 776.351215 623.282374 507.765925 627.708697 241.59199 631.837729 122.411603 767.930632 69.295732 881.396439 64.406957 891.768568 65.166699 903.296826 71.310699 912.975277 78.04928 923.578632 89.973925 929.920826 103.186828 929.953858L673.753022 930.482374C691.986828 930.515406 706.752248 945.280826 706.752248 963.547665 706.752248 981.781471 691.953796 996.54689 673.71999 996.54689"/></svg>`;


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
const binding = ref(false);
const bindErrorMessage = ref('');
const bindSuccessMessage = ref('');
const showUnbindConfirm = ref(false);
const status = ref({
  public: {},
  binding: {},
  config: null,
  plugin_version: '0.3.0',
});

let bindPopupTimer = null;
let bindMessageReceived = false;
let bindPollingLock = false;
let idpLoadTimer = null;

// 步骤状态: 'pending' | 'loading' | 'done' | 'error'
const step1State = ref('pending');
const step2State = ref('pending');
const step3State = ref('pending');

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`);
const isBound = computed(() => Boolean(status.value.binding?.bound));
const isEnabled = computed(() => Boolean(status.value?.public?.enabled));

const step1Title = computed(() => {
  const map = { loading: '正在跳转到 IdP', done: '已跳转至 IdP', error: '跳转失败' };
  return map[step1State.value] || '跳转至 IdP 认证'
});
const step1Desc = computed(() => {
  const map = { loading: '正在打开认证提供商的登录页面...', done: '已成功跳转至身份提供商', error: '请尝试重新发起绑定' };
  return map[step1State.value] || '点击下方按钮，跳转至身份提供商进行认证授权'
});
const step2Title = computed(() => {
  const map = { loading: '等待身份认证', done: '身份认证完成', error: '认证已中断' };
  return map[step2State.value] || '完成身份认证'
});
const step2Desc = computed(() => {
  const map = { loading: '请在弹窗中登录并完成授权...', done: '已通过 IdP 身份认证', error: '窗口已关闭，请重试' };
  return map[step2State.value] || '在 IdP 页面登录并完成授权确认'
});
const step3Title = computed(() => {
  const map = { loading: '正在完成绑定', done: '账号绑定成功', error: '绑定失败' };
  return map[step3State.value] || '自动完成绑定'
});
const step3Desc = computed(() => {
  const map = { loading: '正在将 OIDC 账号与本地用户关联...', done: 'OIDC 账号已成功绑定', error: '绑定过程中发生错误' };
  return map[step3State.value] || '授权完成后自动返回 MoviePilot 并完成绑定'
});

const shortSub = computed(() => {
  const sub = status.value?.binding?.sub || status.value?.binding?.masked_sub;
  if (!sub) return ''
  if (sub.length <= 16) return sub
  return sub.slice(0, 16) + '…'
});

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
  if (idpLoadTimer) {
    clearTimeout(idpLoadTimer);
    idpLoadTimer = null;
  }
}

async function handleBindMessage(event) {
  if (event.origin !== window.location.origin) return
  if (event.data?.type !== 'oidcauth_bind_callback') return
  bindMessageReceived = true;
  window.removeEventListener('message', handleBindMessage);
  clearBindPopupTimer();
  step1State.value = 'done';
  step2State.value = 'done';
  if (event.data.success) {
    step3State.value = 'loading';
    for (let attempt = 0; attempt < 10; attempt++) {
      await loadStatus();
      if (isBound.value) {
        step3State.value = 'done';
        bindSuccessMessage.value = 'OIDC 账号已绑定';
        bindErrorMessage.value = '';
        binding.value = false;
        return
      }
      await new Promise(r => setTimeout(r, 1500));
    }
    step3State.value = 'error';
    bindErrorMessage.value = '绑定失败：未检测到绑定状态，请重试';
    binding.value = false;
  } else {
    step3State.value = 'error';
    bindErrorMessage.value = event.data?.message || '绑定失败';
    binding.value = false;
  }
}

async function bindAccount() {
  binding.value = true;
  bindErrorMessage.value = '';
  bindSuccessMessage.value = '';
  bindMessageReceived = false;
  bindPollingLock = false;
  step1State.value = 'pending';
  step2State.value = 'pending';
  step3State.value = 'pending';
  try {
    const response = await props.api.post(`${pluginBase.value}/bind/start`, {});
    const authorizeUrl = response?.data?.authorize_url;
    if (!response?.success || !authorizeUrl) {
      throw new Error(response?.message || '无法发起绑定')
    }
    step1State.value = 'loading';
    window.addEventListener('message', handleBindMessage);
    const popup = window.open(authorizeUrl, 'moviepilot_oidc_bind', 'width=600,height=720,left=200,top=80');
    if (!popup) {
      window.removeEventListener('message', handleBindMessage);
      step1State.value = 'error';
      throw new Error('浏览器阻止了认证弹窗')
    }
    // 3 秒后假设 IdP 页面已加载完成
    idpLoadTimer = setTimeout(() => {
      if (popup && !popup.closed && step1State.value === 'loading' && !bindMessageReceived) {
        step1State.value = 'done';
        step2State.value = 'loading';
      }
    }, 3000);
    bindPopupTimer = setInterval(async () => {
      if (bindPollingLock) return
      bindPollingLock = true;
      try {
        if (!popup.closed && !bindMessageReceived) {
          await loadStatus();
          if (isBound.value) {
            bindMessageReceived = true;
            clearBindPopupTimer();
            window.removeEventListener('message', handleBindMessage);
            step1State.value = 'done';
            step2State.value = 'done';
            step3State.value = 'done';
            bindSuccessMessage.value = 'OIDC 账号已绑定';
            bindErrorMessage.value = '';
            binding.value = false;
            try { popup.close(); } catch (_) { }
            return
          }
          return
        }
        if (!popup.closed) return
        // 弹窗关闭
        clearBindPopupTimer();
        window.removeEventListener('message', handleBindMessage);
        if (!binding.value) return
        binding.value = false;
        if (bindMessageReceived) return
        // Step1 至少已经完成加载
        if (step1State.value === 'loading') {
          step1State.value = 'done';
        }
        // 用户手动关闭窗口 → step2 打叉
        step2State.value = 'error';
        bindErrorMessage.value = '窗口已关闭，请重试';
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
      showUnbindConfirm.value = false;
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

const isLight = ref(false);

function detectTheme() {
  const html = document.documentElement;
  const cls = html.className || '';
  const dataset = html.dataset || {};
  // Vuetify 3 主题
  if (cls.includes('v-theme--light')) { isLight.value = true; return }
  if (cls.includes('v-theme--dark')) { isLight.value = false; return }
  // data-theme 属性
  if (dataset.theme === 'light') { isLight.value = true; return }
  if (dataset.theme === 'dark') { isLight.value = false; return }
  // 备用: 检查 HTML 是否有 dark class
  if (cls.includes('dark')) { isLight.value = false; return }
  if (cls.includes('light')) { isLight.value = true; return }
  isLight.value = false;
}

let themeObserver = null;

onMounted(() => {
  loadStatus();
  document.documentElement.style.overflow = 'hidden';
  document.body.style.overflow = 'hidden';
  detectTheme();
  themeObserver = new MutationObserver(detectTheme);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });
});
onUnmounted(() => {
  clearBindPopupTimer();
  if (idpLoadTimer) clearTimeout(idpLoadTimer);
  window.removeEventListener('message', handleBindMessage);
  if (themeObserver) { themeObserver.disconnect(); themeObserver = null; }
  document.documentElement.style.overflow = '';
  document.body.style.overflow = '';
});

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", {
    class: _normalizeClass(["oidc-page", { 'oidc-light': isLight.value }])
  }, [
    _cache[18] || (_cache[18] = _createStaticVNode("<div class=\"oidc-bg-decor\" data-v-8a889949><div class=\"oidc-bg-blob oidc-bg-blob-1\" data-v-8a889949></div><div class=\"oidc-bg-blob oidc-bg-blob-2\" data-v-8a889949></div><div class=\"oidc-bg-grid\" data-v-8a889949></div><div class=\"oidc-bg-orb oidc-bg-orb-1\" data-v-8a889949></div><div class=\"oidc-bg-orb oidc-bg-orb-2\" data-v-8a889949></div><div class=\"oidc-bg-orb oidc-bg-orb-3\" data-v-8a889949></div></div>", 1)),
    _createElementVNode("div", _hoisted_1, [
      _cache[15] || (_cache[15] = _createStaticVNode("<div class=\"oidc-card oidc-left\" data-v-8a889949><div class=\"oidc-left-header\" data-v-8a889949><svg class=\"oidc-left-icon\" viewBox=\"0 0 256 256\" xmlns=\"http://www.w3.org/2000/svg\" data-v-8a889949><path d=\"M0 0 C1.7159774 -0.00571094 3.43195101 -0.01267798 5.1479187 -0.02079773 C9.78440331 -0.03866516 14.420698 -0.03757278 19.05720663 -0.03185534 C22.93867373 -0.02875392 26.82010485 -0.03486658 30.70156682 -0.04089409 C39.86422633 -0.0549169 49.02679256 -0.05339698 58.18945312 -0.04199219 C67.61781236 -0.03051545 77.04588698 -0.04458433 86.47420871 -0.07138866 C94.59174844 -0.09359587 102.70919916 -0.10017168 110.82676709 -0.09431225 C115.66502586 -0.0909532 120.50310229 -0.09328739 125.3413353 -0.11056328 C129.8936731 -0.12611042 134.44559166 -0.12199135 138.99791336 -0.10325813 C140.66026483 -0.09959353 142.32264791 -0.10261797 143.98497009 -0.11314392 C159.71978438 -0.20510452 173.23259887 3.06255643 185.08642578 14.02905273 C197.16983172 26.84626875 199.35371432 40.68318478 199.30297852 57.50512695 C199.30868945 59.22110435 199.3156565 60.93707796 199.32377625 62.65304565 C199.34164368 67.28953027 199.34055129 71.92582495 199.33483386 76.56233358 C199.33173243 80.44380068 199.3378451 84.32523181 199.34387261 88.20669377 C199.35789542 97.36935328 199.3563755 106.53191952 199.3449707 115.69458008 C199.33349396 125.12293931 199.34756284 134.55101393 199.37436718 143.97933567 C199.39657439 152.09687539 199.4031502 160.21432611 199.39729077 168.33189404 C199.39393171 173.17015282 199.39626591 178.00822924 199.41354179 182.84646225 C199.42908894 187.39880005 199.42496987 191.95071861 199.40623665 196.50304031 C199.40257205 198.16539178 199.40559649 199.82777486 199.41612244 201.49009705 C199.51072605 217.6771408 195.8756987 230.92781239 184.71142578 243.15405273 C172.1196704 254.89882906 158.19775869 256.8575684 141.79785156 256.80810547 C140.08187416 256.81381641 138.36590055 256.82078345 136.64993286 256.8289032 C132.01344825 256.84677063 127.37715356 256.84567825 122.74064493 256.83996081 C118.85917783 256.83685939 114.97774671 256.84297205 111.09628475 256.84899956 C101.93362523 256.86302237 92.771059 256.86150245 83.60839844 256.85009766 C74.18003921 256.83862091 64.75196458 256.85268979 55.32364285 256.87949413 C47.20610312 256.90170134 39.0886524 256.90827715 30.97108448 256.90241772 C26.1328257 256.89905867 21.29474927 256.90139286 16.45651627 256.91866875 C11.90417847 256.93421589 7.35225991 256.93009682 2.7999382 256.9113636 C1.13758673 256.907699 -0.52479635 256.91072344 -2.18711853 256.92124939 C-18.37416229 257.015853 -31.62483387 253.38082565 -43.85107422 242.21655273 C-55.59585054 229.62479735 -57.55458988 215.70288564 -57.50512695 199.30297852 C-57.51083789 197.58700111 -57.51780494 195.87102751 -57.52592468 194.15505981 C-57.54379212 189.5185752 -57.54269973 184.88228052 -57.5369823 180.24577188 C-57.53388087 176.36430479 -57.53999354 172.48287366 -57.54602104 168.6014117 C-57.56004385 159.43875219 -57.55852393 150.27618595 -57.54711914 141.11352539 C-57.5356424 131.68516616 -57.54971128 122.25709154 -57.57651561 112.8287698 C-57.59872283 104.71123007 -57.60529863 96.59377936 -57.5994392 88.47621143 C-57.59608015 83.63795265 -57.59841435 78.79987623 -57.61569023 73.96164322 C-57.63123737 69.40930542 -57.62711831 64.85738686 -57.60838509 60.30506516 C-57.60472048 58.64271368 -57.60774492 56.98033061 -57.61827087 55.31800842 C-57.71023147 39.58319413 -54.44257052 26.07037965 -43.47607422 14.21655273 C-30.65885821 2.1331468 -16.82194217 -0.05073581 0 0 Z\" fill=\"#4A4A4A\" transform=\"translate(57.10107421875,-0.404052734375)\" data-v-8a889949></path><path d=\"M0 0 C0 34.32 0 68.64 0 104 C-16.13020644 112.06510322 -22.35605626 114.39798452 -38.27734375 109.390625 C-53.56383724 103.68024548 -66.1826518 96.46574615 -73.3125 81.1875 C-75.50841113 71.0064575 -73.61355923 63.74057544 -68 55 C-61.24777412 45.63691345 -46.34487157 37.73869339 -35.11572266 35.64941406 C-30.75915717 34.95508322 -26.38923748 34.44477606 -22 34 C-22 37.96 -22 41.92 -22 46 C-23.753125 46.37125 -25.50625 46.7425 -27.3125 47.125 C-38.37872077 49.94043426 -46.14023219 54.82918742 -53 64 C-55.33496753 68.66993506 -54.70556739 75.43275479 -53.3515625 80.359375 C-49.570809 88.69642117 -42.36239176 92.59291409 -34.55078125 96.703125 C-29.57356032 98.52098787 -24.22671084 99.12888153 -19 100 C-19 69.64 -19 39.28 -19 8 C-2 0 -2 0 0 0 Z\" fill=\"#F8A420\" transform=\"translate(141,72)\" data-v-8a889949></path><path d=\"M0 0 C0 3.96 0 7.92 0 12 C-1.753125 12.37125 -3.50625 12.7425 -5.3125 13.125 C-16.37872077 15.94043426 -24.14023219 20.82918742 -31 30 C-33.33496753 34.66993506 -32.70556739 41.43275479 -31.3515625 46.359375 C-27.10773037 55.71756892 -18.12465664 60.25059563 -9 64 C-5.01277631 65.20838675 -1.08007601 66.125698 3 67 C3 70.63 3 74.26 3 78 C-12.36372613 79.05956732 -29.48013877 71.8793015 -41.1875 62 C-47.86202659 55.50380045 -51.89653202 48.24886937 -52.5 38.875 C-52.33221166 30.66455741 -48.41696623 23.31479679 -43 17.25 C-31.73510393 7.03416299 -15.205855 0 0 0 Z\" fill=\"#B4B4B4\" transform=\"translate(119,106)\" data-v-8a889949></path><path d=\"M0 0 C6.9283588 0.22349545 12.90919374 1.74921905 19.4375 3.9375 C20.23075684 4.20256348 21.02401367 4.46762695 21.84130859 4.74072266 C25.26913827 5.92346706 27.95243761 6.96829174 31 9 C35.00586131 8.68374779 37.63682532 7.0906221 41 5 C41.66 5 42.32 5 43 5 C43.66 13.58 44.32 22.16 45 31 C37.82460361 30.20273373 31.13505374 29.09987112 24.125 27.5625 C23.09375 27.34529297 22.0625 27.12808594 21 26.90429688 C20.01257813 26.68966797 19.02515625 26.47503906 18.0078125 26.25390625 C17.11723145 26.06127197 16.22665039 25.8686377 15.30908203 25.67016602 C13 25 13 25 10 23 C12.64 21.35 15.28 19.7 18 18 C16.12855305 17.17934931 14.25265664 16.3688416 12.375 15.5625 C11.33085937 15.11003906 10.28671875 14.65757813 9.2109375 14.19140625 C6.11314749 13.04198295 3.26789946 12.42688777 0 12 C0 8.04 0 4.08 0 0 Z\" fill=\"#B4B4B4\" transform=\"translate(144,106)\" data-v-8a889949></path></svg><div class=\"oidc-left-titles\" data-v-8a889949><h2 class=\"oidc-left-title\" data-v-8a889949>OIDC 认证</h2><p class=\"oidc-left-sub\" data-v-8a889949>OpenID Connect 账号绑定</p></div></div><p class=\"oidc-left-desc\" data-v-8a889949> 通过绑定 OIDC 账号，你可以使用组织内的统一身份系统直接登录 MoviePilot，无需记忆额外密码，享受更安全便捷的认证体验。 </p><div class=\"oidc-left-tags\" data-v-8a889949><span class=\"oidc-left-tag\" data-v-8a889949>OAuth 2.0</span><div class=\"oidc-left-tag-sep\" data-v-8a889949></div><span class=\"oidc-left-tag\" data-v-8a889949>OpenID Connect</span><div class=\"oidc-left-tag-sep\" data-v-8a889949></div><span class=\"oidc-left-tag\" data-v-8a889949>PKCE</span></div><div class=\"oidc-features\" data-v-8a889949><div class=\"feature-card feature-violet\" data-v-8a889949><div class=\"feature-icon feature-purple\" data-v-8a889949><svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><path d=\"M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4\" data-v-8a889949></path><polyline points=\"10 17 15 12 10 7\" data-v-8a889949></polyline><line x1=\"15\" y1=\"12\" x2=\"3\" y2=\"12\" data-v-8a889949></line></svg></div><div class=\"feature-text\" data-v-8a889949><div class=\"feature-title\" data-v-8a889949>单点登录</div><div class=\"feature-desc\" data-v-8a889949>一次认证，畅享全部服务，无需反复输入密码</div></div></div><div class=\"feature-card feature-blue\" data-v-8a889949><div class=\"feature-icon feature-blue-bg\" data-v-8a889949><svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><path d=\"M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z\" data-v-8a889949></path></svg></div><div class=\"feature-text\" data-v-8a889949><div class=\"feature-title\" data-v-8a889949>免密认证</div><div class=\"feature-desc\" data-v-8a889949>通过 IdP 安全授权，无需在本站存储密码</div></div></div><div class=\"feature-card feature-green\" data-v-8a889949><div class=\"feature-icon feature-green-bg\" data-v-8a889949><svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><path d=\"M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2\" data-v-8a889949></path><circle cx=\"9\" cy=\"7\" r=\"4\" data-v-8a889949></circle><path d=\"M23 21v-2a4 4 0 0 0-3-3.87\" data-v-8a889949></path><path d=\"M16 3.13a4 4 0 0 1 0 7.75\" data-v-8a889949></path></svg></div><div class=\"feature-text\" data-v-8a889949><div class=\"feature-title\" data-v-8a889949>统一账号</div><div class=\"feature-desc\" data-v-8a889949>与组织内其他服务共享同一套用户身份体系</div></div></div><div class=\"feature-card feature-amber\" data-v-8a889949><div class=\"feature-icon feature-yellow-bg\" data-v-8a889949><svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><path d=\"M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z\" data-v-8a889949></path><path d=\"m9 12 2 2 4-4\" data-v-8a889949></path></svg></div><div class=\"feature-text\" data-v-8a889949><div class=\"feature-title\" data-v-8a889949>安全可靠</div><div class=\"feature-desc\" data-v-8a889949>基于 OAuth 2.0 / OpenID Connect 标准协议</div></div></div></div></div>", 1)),
      _createElementVNode("div", _hoisted_2, [
        _createElementVNode("div", _hoisted_3, [
          _createElementVNode("div", {
            class: "oidc-right-bigicon",
            innerHTML: USER_ICON_SVG
          }),
          _createElementVNode("h2", _hoisted_4, _toDisplayString(isBound.value ? 'OIDC 账号' : '绑定 OIDC 账号'), 1),
          (!isBound.value)
            ? (_openBlock(), _createElementBlock("p", _hoisted_5, "点击下方按钮跳转至 IdP 完成授权和绑定"))
            : (_openBlock(), _createElementBlock("div", _hoisted_6, [...(_cache[2] || (_cache[2] = [
                _createElementVNode("span", { class: "oidc-dot" }, null, -1),
                _createTextVNode(" 已绑定 ", -1)
              ]))]))
        ]),
        (!isEnabled.value)
          ? (_openBlock(), _createElementBlock("div", _hoisted_7, [...(_cache[3] || (_cache[3] = [
              _createElementVNode("svg", {
                class: "oidc-disabled-icon",
                viewBox: "0 0 24 24",
                fill: "none",
                stroke: "currentColor",
                "stroke-width": "2",
                "stroke-linecap": "round",
                "stroke-linejoin": "round"
              }, [
                _createElementVNode("path", { d: "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" }),
                _createElementVNode("line", {
                  x1: "12",
                  y1: "9",
                  x2: "12",
                  y2: "13"
                }),
                _createElementVNode("line", {
                  x1: "12",
                  y1: "17",
                  x2: "12.01",
                  y2: "17"
                })
              ], -1),
              _createElementVNode("span", null, "OIDC 认证已关闭，绑定与解绑功能不可用", -1)
            ]))]))
          : _createCommentVNode("", true),
        _createElementVNode("div", _hoisted_8, [
          (!isBound.value)
            ? (_openBlock(), _createElementBlock("div", _hoisted_9, [
                _createElementVNode("div", {
                  class: _normalizeClass(["oidc-step", { 'oidc-step-active': step1State.value !== 'pending', 'oidc-step-done-step': step1State.value === 'done' }])
                }, [
                  _createElementVNode("div", _hoisted_10, [
                    _createElementVNode("div", {
                      class: _normalizeClass(["oidc-step-num", {
                      'oidc-num-done': step1State.value === 'done',
                      'oidc-num-loading': step1State.value === 'loading',
                      'oidc-num-error': step1State.value === 'error'
                    }])
                    }, [
                      (step1State.value === 'done')
                        ? (_openBlock(), _createElementBlock("svg", _hoisted_11, [...(_cache[4] || (_cache[4] = [
                            _createElementVNode("polyline", { points: "20 6 9 17 4 12" }, null, -1)
                          ]))]))
                        : (step1State.value === 'loading')
                          ? (_openBlock(), _createElementBlock("span", _hoisted_12))
                          : (step1State.value === 'error')
                            ? (_openBlock(), _createElementBlock("svg", _hoisted_13, [...(_cache[5] || (_cache[5] = [
                                _createElementVNode("line", {
                                  x1: "18",
                                  y1: "6",
                                  x2: "6",
                                  y2: "18"
                                }, null, -1),
                                _createElementVNode("line", {
                                  x1: "6",
                                  y1: "6",
                                  x2: "18",
                                  y2: "18"
                                }, null, -1)
                              ]))]))
                            : (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                                _createTextVNode("1")
                              ], 64))
                    ], 2)
                  ]),
                  _createElementVNode("div", _hoisted_14, [
                    _createElementVNode("div", _hoisted_15, _toDisplayString(step1Title.value), 1),
                    _createElementVNode("div", _hoisted_16, _toDisplayString(step1Desc.value), 1)
                  ])
                ], 2),
                _createElementVNode("div", {
                  class: _normalizeClass(["oidc-step", { 'oidc-step-active': step2State.value !== 'pending', 'oidc-step-done-step': step2State.value === 'done', 'oidc-step-error-step': step2State.value === 'error' }])
                }, [
                  _createElementVNode("div", _hoisted_17, [
                    _createElementVNode("div", {
                      class: _normalizeClass(["oidc-step-num", {
                      'oidc-num-done': step2State.value === 'done',
                      'oidc-num-loading': step2State.value === 'loading',
                      'oidc-num-error': step2State.value === 'error'
                    }])
                    }, [
                      (step2State.value === 'done')
                        ? (_openBlock(), _createElementBlock("svg", _hoisted_18, [...(_cache[6] || (_cache[6] = [
                            _createElementVNode("polyline", { points: "20 6 9 17 4 12" }, null, -1)
                          ]))]))
                        : (step2State.value === 'loading')
                          ? (_openBlock(), _createElementBlock("span", _hoisted_19))
                          : (step2State.value === 'error')
                            ? (_openBlock(), _createElementBlock("svg", _hoisted_20, [...(_cache[7] || (_cache[7] = [
                                _createElementVNode("line", {
                                  x1: "18",
                                  y1: "6",
                                  x2: "6",
                                  y2: "18"
                                }, null, -1),
                                _createElementVNode("line", {
                                  x1: "6",
                                  y1: "6",
                                  x2: "18",
                                  y2: "18"
                                }, null, -1)
                              ]))]))
                            : (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                                _createTextVNode("2")
                              ], 64))
                    ], 2)
                  ]),
                  _createElementVNode("div", _hoisted_21, [
                    _createElementVNode("div", _hoisted_22, _toDisplayString(step2Title.value), 1),
                    _createElementVNode("div", _hoisted_23, _toDisplayString(step2Desc.value), 1)
                  ])
                ], 2),
                _createElementVNode("div", {
                  class: _normalizeClass(["oidc-step", { 'oidc-step-active': step3State.value !== 'pending', 'oidc-step-done-step': step3State.value === 'done', 'oidc-step-error-step': step3State.value === 'error' }])
                }, [
                  _createElementVNode("div", _hoisted_24, [
                    _createElementVNode("div", {
                      class: _normalizeClass(["oidc-step-num", {
                      'oidc-num-done': step3State.value === 'done',
                      'oidc-num-loading': step3State.value === 'loading',
                      'oidc-num-error': step3State.value === 'error'
                    }])
                    }, [
                      (step3State.value === 'done')
                        ? (_openBlock(), _createElementBlock("svg", _hoisted_25, [...(_cache[8] || (_cache[8] = [
                            _createElementVNode("polyline", { points: "20 6 9 17 4 12" }, null, -1)
                          ]))]))
                        : (step3State.value === 'loading')
                          ? (_openBlock(), _createElementBlock("span", _hoisted_26))
                          : (step3State.value === 'error')
                            ? (_openBlock(), _createElementBlock("svg", _hoisted_27, [...(_cache[9] || (_cache[9] = [
                                _createElementVNode("line", {
                                  x1: "18",
                                  y1: "6",
                                  x2: "6",
                                  y2: "18"
                                }, null, -1),
                                _createElementVNode("line", {
                                  x1: "6",
                                  y1: "6",
                                  x2: "18",
                                  y2: "18"
                                }, null, -1)
                              ]))]))
                            : (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                                _createTextVNode("3")
                              ], 64))
                    ], 2)
                  ]),
                  _createElementVNode("div", _hoisted_28, [
                    _createElementVNode("div", _hoisted_29, _toDisplayString(step3Title.value), 1),
                    _createElementVNode("div", _hoisted_30, _toDisplayString(step3Desc.value), 1)
                  ])
                ], 2)
              ]))
            : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                _createElementVNode("div", _hoisted_31, [
                  _createElementVNode("div", _hoisted_32, [
                    _cache[10] || (_cache[10] = _createElementVNode("span", { class: "oidc-info-row-label" }, [
                      _createElementVNode("svg", {
                        class: "oidc-row-icon",
                        viewBox: "0 0 24 24",
                        fill: "none",
                        stroke: "currentColor",
                        "stroke-width": "2",
                        "stroke-linecap": "round",
                        "stroke-linejoin": "round"
                      }, [
                        _createElementVNode("path", { d: "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" }),
                        _createElementVNode("circle", {
                          cx: "12",
                          cy: "7",
                          r: "4"
                        })
                      ]),
                      _createTextVNode(" 绑定用户 ")
                    ], -1)),
                    _createElementVNode("span", _hoisted_33, _toDisplayString(status.value.binding?.local_username || status.value.binding?.username || status.value.binding?.sub || status.value.binding?.masked_sub || '用户'), 1)
                  ]),
                  _createElementVNode("div", _hoisted_34, [
                    _cache[11] || (_cache[11] = _createStaticVNode("<span class=\"oidc-info-row-label\" data-v-8a889949><svg class=\"oidc-row-icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><circle cx=\"12\" cy=\"12\" r=\"10\" data-v-8a889949></circle><line x1=\"2\" y1=\"12\" x2=\"22\" y2=\"12\" data-v-8a889949></line><path d=\"M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z\" data-v-8a889949></path></svg> OIDC Subject </span>", 1)),
                    _createElementVNode("span", {
                      class: "oidc-info-row-value",
                      title: status.value.binding?.sub || status.value.binding?.masked_sub
                    }, _toDisplayString(shortSub.value), 9, _hoisted_35)
                  ]),
                  _cache[12] || (_cache[12] = _createStaticVNode("<div class=\"oidc-info-row\" data-v-8a889949><span class=\"oidc-info-row-label\" data-v-8a889949><svg class=\"oidc-row-icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><path d=\"M22 11.08V12a10 10 0 1 1-5.93-9.14\" data-v-8a889949></path><polyline points=\"22 4 12 14.01 9 11.01\" data-v-8a889949></polyline></svg> 认证状态 </span><span class=\"oidc-info-row-status\" data-v-8a889949><span class=\"oidc-status-dot\" data-v-8a889949></span> 有效 </span></div>", 1))
                ]),
                _createElementVNode("p", _hoisted_36, " 已通过 OIDC 绑定，可直接使用 " + _toDisplayString(status.value.binding?.local_username || status.value.binding?.username || status.value.binding?.sub || status.value.binding?.masked_sub || 'admin') + " 的身份登录 MoviePilot ", 1)
              ], 64))
        ]),
        _createElementVNode("div", _hoisted_37, [
          (!isBound.value)
            ? (_openBlock(), _createElementBlock("button", {
                key: 0,
                class: "oidc-btn oidc-btn-primary",
                disabled: binding.value || !isEnabled.value,
                onClick: bindAccount
              }, _toDisplayString(isEnabled.value ? '绑定 OIDC 账号' : '认证功能已关闭'), 9, _hoisted_38))
            : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                (showUnbindConfirm.value)
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                      _cache[13] || (_cache[13] = _createElementVNode("p", { class: "oidc-unbind-confirm-text" }, "确认解绑？解绑后将无法使用 OIDC 登录。", -1)),
                      _createElementVNode("div", _hoisted_39, [
                        _createElementVNode("button", {
                          class: "oidc-btn oidc-btn-outline",
                          disabled: binding.value || !isEnabled.value,
                          onClick: _cache[0] || (_cache[0] = $event => (showUnbindConfirm.value = false))
                        }, " 取消 ", 8, _hoisted_40),
                        _createElementVNode("button", {
                          class: "oidc-btn oidc-btn-danger",
                          disabled: binding.value || !isEnabled.value,
                          onClick: unbindAccount
                        }, " 确认解绑 ", 8, _hoisted_41)
                      ])
                    ], 64))
                  : (_openBlock(), _createElementBlock("button", {
                      key: 1,
                      class: "oidc-btn oidc-btn-unbind",
                      disabled: !isEnabled.value,
                      onClick: _cache[1] || (_cache[1] = $event => (showUnbindConfirm.value = true))
                    }, [...(_cache[14] || (_cache[14] = [
                      _createElementVNode("svg", {
                        class: "oidc-btn-icon",
                        viewBox: "0 0 24 24",
                        fill: "none",
                        stroke: "currentColor",
                        "stroke-width": "2",
                        "stroke-linecap": "round",
                        "stroke-linejoin": "round"
                      }, [
                        _createElementVNode("path", { d: "M18 6 6 18" }),
                        _createElementVNode("path", { d: "m6 6 12 12" })
                      ], -1),
                      _createTextVNode(" 解绑 OIDC 账号 ", -1)
                    ]))], 8, _hoisted_42))
              ], 64))
        ]),
        _createVNode(_Transition, { name: "oidc-fade" }, {
          default: _withCtx(() => [
            (bindErrorMessage.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_43, _toDisplayString(bindErrorMessage.value), 1))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }),
        _createVNode(_Transition, { name: "oidc-fade" }, {
          default: _withCtx(() => [
            (bindSuccessMessage.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_44, _toDisplayString(bindSuccessMessage.value), 1))
              : _createCommentVNode("", true)
          ]),
          _: 1
        })
      ])
    ]),
    _createElementVNode("div", _hoisted_45, [
      _cache[17] || (_cache[17] = _createElementVNode("div", { class: "oidc-bottom-line" }, null, -1)),
      _createElementVNode("div", _hoisted_46, [
        _cache[16] || (_cache[16] = _createStaticVNode("<div class=\"oidc-bottom-left\" data-v-8a889949><svg class=\"oidc-warn-icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" data-v-8a889949><path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z\" data-v-8a889949></path><line x1=\"12\" y1=\"9\" x2=\"12\" y2=\"13\" data-v-8a889949></line><line x1=\"12\" y1=\"17\" x2=\"12.01\" y2=\"17\" data-v-8a889949></line></svg> 请注意保管 OIDC 资料，以免信息泄露 </div>", 1)),
        _createElementVNode("div", _hoisted_47, "OIDCAuth v" + _toDisplayString(status.value.plugin_version || '0.3.0'), 1)
      ])
    ])
  ], 2))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-8a889949"]]);

export { AppPage as default };
