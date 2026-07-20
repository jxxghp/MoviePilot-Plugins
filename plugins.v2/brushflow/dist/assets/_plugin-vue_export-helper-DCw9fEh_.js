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
    result[key] = result[key] === '' || result[key] === null ? null : Number(result[key]);
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
    disabled: { text: '插件停用', color: 'secondary', icon: 'mdi-stop-circle-outline' },
    error: { text: '运行异常', color: 'error', icon: 'mdi-alert-circle-outline' },
  };
  return states[state] || states.running
}

/** 根据已下载量和总大小计算种子完成百分比。 */
function torrentProgress(item) {
  const size = Number(item?.size || 0);
  if (!size) return 0
  return Math.min(Math.round((Number(item.downloaded || 0) * 100) / size), 100)
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

export { _export_sfc as _, formatDateTime as a, formatDuration as b, cloneTask as c, torrentProgress as d, formatBytes as f, normalizeTask as n, taskStateMeta as t, unwrapResponse as u };
