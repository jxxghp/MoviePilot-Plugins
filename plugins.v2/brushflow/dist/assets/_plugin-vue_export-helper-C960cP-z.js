const __mfPromiseGlobalKey = "__mf_init__virtual:mf:__mfe_internal__BrushFlow__mf_owner__217245097701611__mf_v__runtimeInit__mf_v__.js__";
let __mfPromiseState = globalThis[__mfPromiseGlobalKey];
if (!__mfPromiseState) {
  let initResolve, initReject;
  const initPromise = new Promise((re, rj) => {
    initResolve = re;
    initReject = rj;
  });
  __mfPromiseState = globalThis[__mfPromiseGlobalKey] = {
    initPromise,
    initResolve,
    initReject,
  };
  
}
const initPromise = __mfPromiseState.initPromise;

    
const __mfCacheGlobalKey = "__mf_module_cache__";
globalThis[__mfCacheGlobalKey] ||= { share: {}, remote: {} };
globalThis[__mfCacheGlobalKey].share ||= {};
globalThis[__mfCacheGlobalKey].remote ||= {};
const __mfModuleCache = globalThis[__mfCacheGlobalKey];
const __mfTrackPendingShareLoad = (promise) => {
  const pendingShareLoads = (__mfModuleCache.pendingShareLoads ||= []);
  pendingShareLoads.push(promise);
  const cleanup = () => {
    const index = pendingShareLoads.indexOf(promise);
    if (index !== -1) pendingShareLoads.splice(index, 1);
  };
  void promise.then(cleanup, cleanup);
  return promise;
};
for (const __mfShareKey of Object.keys(__mfModuleCache.share)) {
  if (__mfShareKey.startsWith("default:")) {
    const __mfLegacyShareKey = __mfShareKey.slice("default:".length);
    if (__mfModuleCache.share[__mfLegacyShareKey] === undefined) {
      __mfModuleCache.share[__mfLegacyShareKey] = __mfModuleCache.share[__mfShareKey];
    }
  } else if (!__mfShareKey.includes(":")) {
    const __mfDefaultShareKey = "default:" + __mfShareKey;
    if (__mfModuleCache.share[__mfDefaultShareKey] === undefined) {
      __mfModuleCache.share[__mfDefaultShareKey] = __mfModuleCache.share[__mfShareKey];
    }
  }
}
          const __mfReadSharedCache = (cache, descriptor) => {
            const value = cache[descriptor.canonical];
            if (value !== undefined) return value;
            const aliases = descriptor.aliases || [];
            for (const alias of aliases) {
              if (!Object.prototype.hasOwnProperty.call(cache, alias)) continue;
              const aliasValue = cache[alias];
              if (aliasValue !== undefined) {
                cache[descriptor.canonical] = aliasValue;
                return aliasValue;
              }
            }
            return undefined;
          };
          const __mfSharedCacheListenersKey = Symbol.for("module-federation.shared-cache-listeners");
          const __mfGetSharedCacheListeners = (cache) => {
            let listeners = cache[__mfSharedCacheListenersKey];
            if (listeners === undefined) {
              listeners = Object.create(null);
              Object.defineProperty(cache, __mfSharedCacheListenersKey, {
                value: listeners,
                enumerable: false,
                configurable: false,
                writable: false
              });
            }
            return listeners;
          };
          const __mfSubscribeSharedCache = (cache, descriptor, listener) => {
            const listeners = __mfGetSharedCacheListeners(cache);
            (listeners[descriptor.canonical] ||= new Set()).add(listener);
          };
    let __mf_0;
    let __mf_1;
    let __mf_2;
    let __mf_3;
    let __mf_4;
    let __mf_5;
    let __mf_6;
    let __mf_7;
    let __mf_8;
    let __mf_9;
    let __mf_10;
    let __mf_11;
    let __mf_12;
    let __mf_13;
    let __mf_14;
    let __mf_15;
    let __mf_16;
    let __mf_17;
    let __mf_18;
    let __mf_19;
    let __mf_20;
    let __mf_21;
    let __mf_22;
    let __mf_23;
    const __mfApplyHostProvidedExports = (exportModule) => {
      __mf_0 = exportModule["createApp"];
      __mf_1 = exportModule["withModifiers"];
      __mf_2 = exportModule["ref"];
      __mf_3 = exportModule["unref"];
      __mf_4 = exportModule["normalizeClass"];
      __mf_5 = exportModule["normalizeStyle"];
      __mf_6 = exportModule["toDisplayString"];
      __mf_7 = exportModule["Fragment"];
      __mf_8 = exportModule["computed"];
      __mf_9 = exportModule["createBlock"];
      __mf_10 = exportModule["createCommentVNode"];
      __mf_11 = exportModule["createElementBlock"];
      __mf_12 = exportModule["createElementVNode"];
      __mf_13 = exportModule["createTextVNode"];
      __mf_14 = exportModule["createVNode"];
      __mf_15 = exportModule["inject"];
      __mf_16 = exportModule["mergeProps"];
      __mf_17 = exportModule["onMounted"];
      __mf_18 = exportModule["onUnmounted"];
      __mf_19 = exportModule["openBlock"];
      __mf_20 = exportModule["renderList"];
      __mf_21 = exportModule["resolveComponent"];
      __mf_22 = exportModule["watch"];
      __mf_23 = exportModule["withCtx"];
      exportModule.default ?? exportModule;
    };
    let exportModule = __mfReadSharedCache(__mfModuleCache.share, {"canonical":"default:vue","aliases":["vue"]});
    if (exportModule === undefined) {
      __mfSubscribeSharedCache(__mfModuleCache.share, {"canonical":"default:vue"}, (mod) => {
        exportModule = mod;
        __mfApplyHostProvidedExports(mod);
      });
      __mfTrackPendingShareLoad(initPromise.then(() => {
        exportModule = __mfReadSharedCache(__mfModuleCache.share, {"canonical":"default:vue","aliases":["vue"]});
        // A share init() left to its dynamic import is normally bridged before that import runs;
        // bridge it here when this wrapper is reached another way.
        if (exportModule === undefined && typeof __mfPromiseState.loadLazyShares === "function") {
          return __mfPromiseState.loadLazyShares(["vue"]).then(() => {
            exportModule = __mfReadSharedCache(__mfModuleCache.share, {"canonical":"default:vue","aliases":["vue"]});
          });
        }
      }).then(() => {
        if (exportModule === undefined) {
          throw new Error("[Module Federation] Shared module vue was imported before federation bootstrap finished.");
        }
        __mfApplyHostProvidedExports(exportModule);
      }));
    } else {
      __mfApplyHostProvidedExports(exportModule);
    }

const taskDefaults = {
  id: '',
  name: '',
  enabled: true,
  notify: true,
  site_id: null,
  downloader: '',
  brush_interval: 10,
  check_interval: 5,
  cron: null,
  active_time_range: null,
  site_ratio_control: false,
  site_ratio_target: null,
  disksize: null,
  maxupspeed: null,
  maxdlspeed: null,
  maxdlcount: null,
  freeleech: 'free',
  hr: 'yes',
  include: null,
  exclude: null,
  size: null,
  seeder: null,
  timezone_offset: 0,
  pubtime: null,
  seed_time: null,
  hr_seed_time: null,
  seed_ratio: null,
  seed_size: null,
  download_time: null,
  seed_avgspeed: null,
  seed_inactivetime: null,
  delete_size_range: null,
  up_speed: null,
  dl_speed: null,
  auto_archive_days: null,
  save_path: null,
  delete_except_tags: null,
  except_subscribe: true,
  proxy_delete: false,
  del_no_free: false,
  qb_category: null,
  site_hr_active: false,
  site_skip_tips: false,
  rss_support: false,
};

/** 统一提取宿主 API 客户端与标准响应模型中的业务数据。 */
function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'success')) {
    if (response.success === false) throw new Error(response.message || '操作失败')
    return response.data
  }
  return response?.data ?? response
}

/** 基于完整默认值创建可安全编辑的任务深拷贝。 */
function cloneTask(task = {}) {
  return JSON.parse(JSON.stringify({ ...taskDefaults, ...(task || {}) }))
}

/** 把表单空值和数字字段标准化为后端请求模型需要的类型。 */
function normalizeTask(task) {
  const result = cloneTask(task);
  const nullableNumbers = [
    'disksize',
    'maxupspeed',
    'maxdlspeed',
    'maxdlcount',
    'site_ratio_target',
    'seed_time',
    'hr_seed_time',
    'seed_ratio',
    'seed_size',
    'download_time',
    'seed_avgspeed',
    'seed_inactivetime',
    'up_speed',
    'dl_speed',
    'auto_archive_days',
  ];
  const optionalText = [
    'cron',
    'active_time_range',
    'include',
    'exclude',
    'size',
    'seeder',
    'pubtime',
    'delete_size_range',
    'save_path',
    'delete_except_tags',
    'qb_category',
  ];
  nullableNumbers.forEach(key => {
    const value = result[key] === '' || result[key] === null ? null : Number(result[key]);
    result[key] = value === 0 ? null : value;
  });
  optionalText.forEach(key => {
    result[key] = String(result[key] || '').trim() || null;
  });
  result.site_id = Number(result.site_id);
  result.brush_interval = Number(result.brush_interval || 10);
  result.check_interval = Number(result.check_interval || 5);
  result.timezone_offset = Number(result.timezone_offset || 0);
  return result
}

/** 把全局设置中的空值、零值和正数标准化为后端请求类型。 */
function normalizeSettings(settings = {}) {
  const result = { ...(settings || {}) };
  const limitFields = ['global_disksize', 'global_maxdlcount', 'global_maxupspeed', 'global_maxdlspeed'];
  limitFields.forEach(key => {
    const value = Number(result[key] || 0);
    result[key] = value > 0 ? value : null;
  });
  result.global_proxy_delete = Boolean(result.global_proxy_delete);
  result.global_delete_size_range = result.global_proxy_delete
    ? String(result.global_delete_size_range || '').trim() || null
    : null;
  return result
}

/** 将字节数格式化为适合紧凑界面展示的容量文本。 */
function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const number = bytes / 1024 ** index;
  return `${number >= 100 ? number.toFixed(0) : number.toFixed(1)} ${units[index]}`
}

/** 将时间值格式化为当前界面使用的月日与时分。 */
function formatDateTime(value) {
  if (!value) return '暂无'
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** 计算一次运行记录的秒级耗时。 */
function formatDuration(startedAt, finishedAt) {
  if (!startedAt || !finishedAt) return '-'
  const seconds = Math.max(Math.round((new Date(finishedAt) - new Date(startedAt)) / 1000), 0);
  return `${seconds} 秒`
}

/** 返回任务状态对应的中文文本、主题色和图标。 */
function taskStateMeta(state) {
  const states = {
    running: { text: '运行中', color: 'success', icon: 'mdi-check-circle-outline' },
    brush: { text: '正在刷新', color: 'primary', icon: 'mdi-sync' },
    check: { text: '正在检查', color: 'info', icon: 'mdi-progress-check' },
    paused: { text: '已暂停', color: 'secondary', icon: 'mdi-pause-circle-outline' },
    waiting: { text: '等待时段', color: 'warning', icon: 'mdi-clock-outline' },
    waiting_ratio: { text: '待刷流', color: 'warning', icon: 'mdi-target' },
    ratio_unavailable: { text: '等待数据', color: 'info', icon: 'mdi-database-clock-outline' },
    disabled: { text: '插件停用', color: 'secondary', icon: 'mdi-stop-circle-outline' },
    error: { text: '运行异常', color: 'error', icon: 'mdi-alert-circle-outline' },
  };
  return states[state] || states.running
}

/** 优先使用下载器文件完成度，旧记录兼容下载量；未完成时不舍入成做种。 */
function torrentProgress(item) {
  const size = Number(item?.size || 0);
  const progress = item?.progress != null
    ? Number(item.progress)
    : size > 0 ? Number(item?.downloaded || 0) / size : 0;
  if (!Number.isFinite(progress)) return 0
  if (progress >= 1) return 100
  return Math.max(0, Math.min(Math.round(progress * 100), 99))
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

export { __mf_4 as A, __mf_16 as B, formatDateTime as C, formatDuration as D, torrentProgress as E, __mf_5 as F, normalizeSettings as G, __mf_0 as _, __mf_19 as a, __mf_9 as b, __mf_17 as c, _export_sfc as d, __mf_2 as e, __mf_8 as f, __mf_22 as g, __mf_18 as h, __mf_21 as i, __mf_11 as j, __mf_12 as k, __mf_6 as l, __mf_3 as m, formatBytes as n, __mf_14 as o, __mf_7 as p, __mf_20 as q, __mf_13 as r, __mf_10 as s, taskStateMeta as t, unwrapResponse as u, cloneTask as v, __mf_23 as w, __mf_1 as x, normalizeTask as y, __mf_15 as z };
