import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

/** 按二进制 1024 进位将字节数格式化为 MoviePilot 一致的容量文本。 */
function formatBytes(value) {
  let bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) {
    bytes /= 1024;
    index += 1;
  }
  if (index === 0) return `${Math.round(bytes)} ${units[index]}`
  const digits = bytes < 100 ? 2 : 1;
  return `${bytes.toFixed(digits)} ${units[index]}`
}

/** 兼容宿主 API、标准业务响应和 Axios 响应的常见包装形式。 */
function unwrapResponse(response) {
  let value = response;
  for (let depth = 0; depth < 2; depth += 1) {
    if (!value || typeof value !== 'object') return value
    if (Object.prototype.hasOwnProperty.call(value, 'success')) {
      if (value.success === false) throw new Error(value.message || '操作失败')
      value = value.data;
      continue
    }
    if (Object.prototype.hasOwnProperty.call(value, 'data')) {
      value = value.data;
      continue
    }
    break
  }
  return value
}

/** 格式化普通数值，并为缺失值保留明确状态。 */
function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '站点未提供'
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value)
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: digits }).format(number)
}

/** 点击日期输入框的任意位置时打开浏览器原生日期选择器。 */
function openNativePicker(event) {
  const current = event?.currentTarget;
  const fallback = event?.target?.closest?.('.v-input');
  const input = current?.matches?.('input')
    ? current
    : current?.querySelector?.('input') || fallback?.querySelector?.('input');
  if (!input) return
  input.focus();
  if (typeof input.showPicker !== 'function') return
  // 由 showPicker 统一处理本次点击，避免浏览器默认动作再次打开控件。
  event?.preventDefault?.();
  try {
    input.showPicker();
  } catch {
    // 某些浏览器仅允许在受信任点击中调用，焦点仍可触发原生回退行为。
  }
}

/** 创建包含重复查询参数的 URL。 */
function withQuery(path, query = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return
    params.set(key, Array.isArray(value) ? value.join(',') : String(value));
  });
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path
}

const iconCache = new Map();

/** 通过宿主站点图标 API 获取图标并跨组件缓存。 */
async function getSiteIcon(api, siteId) {
  if (!siteId) return ''
  if (iconCache.has(siteId)) return iconCache.get(siteId)
  try {
    const response = await api.get(`site/icon/${siteId}`, { feedback: 'silent' });
    const data = unwrapResponse(response);
    const icon = typeof data === 'string' ? data : data?.icon || data?.base64 || data?.url || '';
    iconCache.set(siteId, icon);
    return icon
  } catch {
    iconCache.set(siteId, '');
    return ''
  }
}

/** 今日站点分布使用的稳定配色。 */
const siteColors = [
  '#6ee7b7',
  '#84cc16',
  '#22d3ee',
  '#8b5cf6',
  '#f59e0b',
  '#fb7185',
  '#60a5fa',
  '#a78bfa',
  '#2dd4bf',
  '#f97316',
  '#e879f9',
  '#38bdf8',
];

const {resolveComponent:_resolveComponent,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createElementBlock:_createElementBlock,withCtx:_withCtx} = await importShared('vue');


const _hoisted_1 = {
  key: 1,
  class: "font-weight-bold"
};

const {computed,onMounted,ref,watch} = await importShared('vue');


const _sfc_main = {
  __name: 'SiteAvatar',
  props: {
  api: { type: Object, default: () => ({}) },
  site: { type: Object, default: () => ({}) },
  size: { type: [Number, String], default: 34 },
},
  setup(__props) {

const props = __props;

const icon = ref('');
const fallback = computed(() => String(props.site?.site_name || '?').trim().slice(0, 1).toUpperCase());

async function loadIcon() {
  icon.value = await getSiteIcon(props.api, props.site?.site_id);
}

watch(() => props.site?.site_id, loadIcon);
onMounted(loadIcon);

return (_ctx, _cache) => {
  const _component_VImg = _resolveComponent("VImg");
  const _component_VAvatar = _resolveComponent("VAvatar");

  return (_openBlock(), _createBlock(_component_VAvatar, {
    size: __props.size,
    color: "primary",
    variant: "tonal"
  }, {
    default: _withCtx(() => [
      (icon.value)
        ? (_openBlock(), _createBlock(_component_VImg, {
            key: 0,
            src: icon.value,
            alt: __props.site.site_name
          }, null, 8, ["src", "alt"]))
        : (_openBlock(), _createElementBlock("span", _hoisted_1, _toDisplayString(fallback.value), 1))
    ]),
    _: 1
  }, 8, ["size"]))
}
}

};

export { _export_sfc as _, _sfc_main as a, formatNumber as b, formatBytes as f, openNativePicker as o, siteColors as s, unwrapResponse as u, withQuery as w };
