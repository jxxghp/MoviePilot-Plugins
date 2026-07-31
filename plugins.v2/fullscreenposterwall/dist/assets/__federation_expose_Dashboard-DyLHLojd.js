import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { D as DepthTunnel, R as RingGallery, S as SlidingPanels, a as ShiftingTiles, L as LightDance, V as VintagePrints, F as Floating, P as PhotosSlideshow } from './DepthTunnel-Dx7GfZGR.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,resolveDynamicComponent:_resolveDynamicComponent,openBlock:_openBlock,createBlock:_createBlock,normalizeStyle:_normalizeStyle,normalizeClass:_normalizeClass,Fragment:_Fragment,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,Teleport:_Teleport} = await importShared('vue');


const _hoisted_1 = { class: "fspw-dash" };
const _hoisted_2 = { class: "dash-header" };
const _hoisted_3 = { class: "dash-play-hint" };

const {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} = await importShared('vue');

const API_BASE = 'plugin/FullScreenPosterWall';


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
},
  setup(__props) {

// Dashboard 组件 — MoviePilot 主页面的仪表板小窗格。
//
// 核心改进：
// - "全屏播放"按钮不再跳转路由；点击直接在 dashboard 卡片内部渲染完整动效。
// - 动效由用户保存的插件 config 完全控制（effect / interval / image_type / shuffle / hide_text）。
// - 进入浏览器原生全屏 API（Fullscreen API），把整个 dashboard 卡扩展到整个屏幕。
const props = __props;

function getApi() { return (typeof window !== 'undefined' ? window.MoviePilotAPI : null) }

const items = ref([]);
const fullscreen = ref(false);
const fullRef = ref(null);
const stageRef = ref(null);
// 本地拉取的插件配置：Config 保存后以此为准（设置的唯一数据源），
// props.config 仅作为首帧兜底，之后每 5 秒轮询刷新一次。
const localConfig = ref({});
const cfg = computed(() => ({ ...(props.config || {}), ...(localConfig.value || {}) }));
let configPollTimer;
let fsChangeHandler;

const effectMap = {
  photos: PhotosSlideshow,
  floating: Floating,
  vintage: VintagePrints,
  lightdance: LightDance,
  shiftingtiles: ShiftingTiles,
  slidingpanels: SlidingPanels,
  ring3d: RingGallery,
  depthtunnel: DepthTunnel,
};
const currentEffectComp = computed(() => effectMap[cfg.value?.effect || 'photos'] || PhotosSlideshow);
const effectName = computed(() => {
  const map = {
    photos: '照片', floating: '浮动', vintage: '怀旧冲印',
    lightdance: '光舞',
    shiftingtiles: '流动拼贴', slidingpanels: '滑动面板',
    ring3d: '环形画廊', depthtunnel: '纵深穿梭',
  };
  return map[cfg.value?.effect || 'photos'] || '照片'
});
const hideText = computed(() => !!cfg.value?.hide_text);

// 小窗格缩放系数：按窗格与视口的比例整体缩放动效（vw/px 单位都生效）
const stageZoom = ref(0.2);
function updateStageZoom() {
  const el = stageRef.value;
  if (!el) return
  stageZoom.value = Math.min(
    el.clientWidth / window.innerWidth,
    el.clientHeight / window.innerHeight
  );
}

async function loadData(forceShuffle = false) {
  const api = getApi();
  if (!api?.get) return
  try {
    const url = forceShuffle
      ? `${API_BASE}/recommend?shuffle=true`
      : `${API_BASE}/recommend`;
    const raw = await api.get(url);
    let list = [];
    if (Array.isArray(raw)) list = raw;
    else if (Array.isArray(raw?.data)) list = raw.data;
    items.value = list;
  } catch (e) {
    console.warn('[FullScreenPosterWall-Dashboard] load failed', e);
  }
}

async function loadConfig() {
  const api = getApi();
  if (!api?.get) return
  try {
    const raw = await api.get(`${API_BASE}/config`);
    const c = raw?.data ?? raw;
    if (c && typeof c === 'object') {
      const changed = JSON.stringify(localConfig.value) !== JSON.stringify(c);
      if (changed) localConfig.value = c;
    }
  } catch (e) {
    console.warn('[FullScreenPosterWall-Dashboard] loadConfig failed', e);
  }
}

async function enterFullscreen() {
  // 进入全屏前强制刷新数据，避免用过时的轮播序列
  if (props.allowRefresh) {
    await loadData(true);
  }
  fullscreen.value = true;
  await nextTick();
  // 尝试调用浏览器原生 Fullscreen API（用户手势后调用，浏览器允许）
  const el = fullRef.value;
  if (el) {
    try {
      if (el.requestFullscreen) await el.requestFullscreen();
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    } catch (e) {
      // 浏览器拒绝权限时，留在应用内全屏（容器已经 fixed 100vw/100vh）
      console.warn('[FullScreenPosterWall-Dashboard] requestFullscreen denied, stay in-app fullscreen', e);
    }
  }
}

/**
 * 在 LAN 模式下其他设备打开分享 URL 时，主框架跳到 /#/dashboard，
 * MoviePilot 渲染 dashboard.vue，里面有我们的 widget。
 *
 * 检测 query string ?fullscreen=1 / ?auto=1：用户首次访问时
 * 跳过 dashboard 直接进全屏。但 MoviePilot 默认行为是先登录，
 * 所以实际更现实的是 dashboard widget 监听 hash 里的 _lan=auto。
 */
function maybeStartFullscreenFromQuery() {
  try {
    const sp = new URLSearchParams(location.search);
    if (sp.get('fullscreen') === '1' || sp.get('auto') === '1') {
      fullscreen.value = true;
      // 同时请求浏览器全屏
      nextTick(() => {
        const el = fullRef.value;
        if (el?.requestFullscreen) {
          el.requestFullscreen().catch(() => {});
        }
      });
    }
  } catch {}
}

async function exitFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
  } catch {}
  fullscreen.value = false;
}

// 监听浏览器全屏状态变化：用户按 Esc 退出屏幕全屏时，同步退出应用内全屏
function onFsChange() {
  if (!document.fullscreenElement && fullscreen.value) {
    fullscreen.value = false;
  }
}

function onKey(e) {
  if (fullscreen.value && e.key === 'Escape') exitFullscreen();
}

let stageObserver = null;
onMounted(async () => {
  await loadConfig();
  await loadData(true);
  nextTick(() => {
    updateStageZoom();
    // 窗格尺寸变化（侧栏折叠/布局调整）时自动重新适配
    if (stageRef.value && typeof ResizeObserver !== 'undefined') {
      stageObserver = new ResizeObserver(() => updateStageZoom());
      stageObserver.observe(stageRef.value);
    }
  });
  window.addEventListener('resize', updateStageZoom);
  fsChangeHandler = onFsChange;
  document.addEventListener('fullscreenchange', fsChangeHandler);
  window.addEventListener('keydown', onKey);
  // 5 秒轮询插件配置：Config 弹窗保存后卡片自动用上新设置
  configPollTimer = window.setInterval(loadConfig, 5000);
  // 检测 URL query：如果带 ?fullscreen=1 / ?auto=1，自动进入全屏
  maybeStartFullscreenFromQuery();
});

onBeforeUnmount(() => {
  if (configPollTimer) clearInterval(configPollTimer);
  stageObserver?.disconnect();
  window.removeEventListener('resize', updateStageZoom);
  if (fsChangeHandler) document.removeEventListener('fullscreenchange', fsChangeHandler);
  window.removeEventListener('keydown', onKey);
  // 万一用户在 dashboard 卡片里全屏时切走，清理浏览器全屏
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
});

return (_ctx, _cache) => {
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (!fullscreen.value)
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
          _createElementVNode("div", _hoisted_2, [
            _cache[0] || (_cache[0] = _createElementVNode("span", { class: "dash-icon" }, "🎬", -1)),
            _cache[1] || (_cache[1] = _createElementVNode("span", { class: "dash-title" }, "全屏海报墙", -1)),
            _createVNode(_component_v_chip, {
              size: "x-small",
              class: "ml-2",
              color: "primary",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(effectName.value), 1)
              ]),
              _: 1
            })
          ]),
          _createElementVNode("div", {
            ref_key: "stageRef",
            ref: stageRef,
            class: _normalizeClass(["dash-stage", { 'dash-no-text': hideText.value }]),
            onClick: enterFullscreen,
            title: "点击进入全屏"
          }, [
            _createElementVNode("div", {
              class: "dash-effect-zoom",
              style: _normalizeStyle({ zoom: stageZoom.value })
            }, [
              (_openBlock(), _createBlock(_resolveDynamicComponent(currentEffectComp.value), {
                items: items.value,
                interval: cfg.value.interval || 8,
                "image-type": cfg.value.image_type || 'backdrop',
                autoplay: false
              }, null, 8, ["items", "interval", "image-type"]))
            ], 4),
            _createElementVNode("div", _hoisted_3, [
              _createVNode(_component_v_icon, { size: "large" }, {
                default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
                  _createTextVNode("mdi-play-circle-outline", -1)
                ]))]),
                _: 1
              })
            ])
          ], 2),
          _createVNode(_component_v_btn, {
            color: "primary",
            variant: "tonal",
            block: "",
            class: "dash-cta mt-3",
            "prepend-icon": "mdi-play-circle-outline",
            onClick: enterFullscreen
          }, {
            default: _withCtx(() => [...(_cache[3] || (_cache[3] = [
              _createTextVNode(" 全屏播放 ", -1)
            ]))]),
            _: 1
          })
        ], 64))
      : _createCommentVNode("", true),
    (_openBlock(), _createBlock(_Teleport, { to: "body" }, [
      (fullscreen.value)
        ? (_openBlock(), _createElementBlock("div", {
            key: 0,
            ref_key: "fullRef",
            ref: fullRef,
            class: _normalizeClass(["dash-fullscreen", { 'dash-no-text': hideText.value }])
          }, [
            (_openBlock(), _createBlock(_resolveDynamicComponent(currentEffectComp.value), {
              items: items.value,
              interval: cfg.value.interval || 8,
              "image-type": cfg.value.image_type || 'backdrop',
              autoplay: true
            }, null, 8, ["items", "interval", "image-type"])),
            _createElementVNode("button", {
              class: "dash-exit",
              onClick: exitFullscreen,
              title: "退出 (Esc)"
            }, "✕")
          ], 2))
        : _createCommentVNode("", true)
    ]))
  ]))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-338ef4ef"]]);

export { Dashboard as default };
