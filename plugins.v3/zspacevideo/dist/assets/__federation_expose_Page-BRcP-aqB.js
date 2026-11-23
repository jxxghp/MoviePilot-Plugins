import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {toDisplayString:_toDisplayString$1,createTextVNode:_createTextVNode$1,resolveComponent:_resolveComponent$1,withCtx:_withCtx$1,openBlock:_openBlock$1,createBlock:_createBlock$1,createCommentVNode:_createCommentVNode$1,createVNode:_createVNode$1,createElementVNode:_createElementVNode$1,createElementBlock:_createElementBlock$1,renderList:_renderList$1,Fragment:_Fragment$1,withModifiers:_withModifiers,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1$1 = { class: "d-flex flex-wrap align-center ga-3 mb-3" };
const _hoisted_2$1 = { class: "text-caption" };
const _hoisted_3$1 = {
  key: 0,
  class: "text-caption text-error"
};
const _hoisted_4$1 = {
  key: 2,
  class: "text-medium-emphasis pa-4"
};
const _hoisted_5$1 = {
  key: 0,
  class: "text-caption"
};
const _hoisted_6$1 = {
  key: 1,
  class: "text-error"
};
const _hoisted_7$1 = {
  key: 0,
  class: "text-error text-caption"
};
const _hoisted_8$1 = ["onClick"];
const _hoisted_9$1 = {
  key: 0,
  class: "text-medium-emphasis"
};
const _hoisted_10$1 = { key: 1 };
const _hoisted_11$1 = { key: 0 };
const _hoisted_12$1 = { class: "text-caption" };
const _hoisted_13$1 = { key: 0 };
const _hoisted_14$1 = {
  colspan: "5",
  class: "pb-3"
};
const _hoisted_15$1 = { key: 0 };
const _hoisted_16$1 = {
  key: 1,
  class: "text-error"
};
const _hoisted_17$1 = {
  key: 2,
  class: "text-warning"
};
const _hoisted_18$1 = {
  key: 0,
  class: "text-warning"
};
const _hoisted_19$1 = { class: "text-caption" };
const _hoisted_20$1 = { class: "text-caption" };
const _hoisted_21$1 = { class: "text-caption" };
const _hoisted_22$1 = { key: 0 };
const _hoisted_23 = {
  key: 1,
  class: "text-error"
};
const _hoisted_24 = { class: "text-caption text-medium-emphasis mb-3" };
const _hoisted_25 = { key: 0 };
const _hoisted_26 = { key: 0 };
const _hoisted_27 = { key: 0 };
const _hoisted_28 = {
  key: 0,
  class: "text-caption"
};

const {computed: computed$1,onMounted: onMounted$1,ref: ref$1} = await importShared('vue');



const _sfc_main$1 = {
  __name: 'Watched',
  props: {
  api: { type: Object, default: () => ({}) },
  base: { type: String, default: 'plugin/ZSpaceVideo' },
},
  setup(__props) {

const props = __props;

const items = ref$1([]);
const meta = ref$1({});
const settings = ref$1({});
const history = ref$1([]);
const loading = ref$1(false);
const syncing = ref$1(false);
const error = ref$1('');
const notice = ref$1('');
const expanded = ref$1({});

const dialog = ref$1(false);
const target = ref$1(null);
const mode = ref$1('library');
const selected = ref$1([]);
const confirmUnknown = ref$1(false);
const plan = ref$1(null);
const previewing = ref$1(false);
const executing = ref$1(false);
const result = ref$1(null);

const MODE_LABELS = { none: '不删', library: '只从库里移除', full: '真删除' };
const MODE_HINTS = {
  library: '删掉库里的入口（硬链接），下载目录里的文件继续做种，不腾空间。极影视里这部片会消失。',
  full: '库入口、下载目录里的做种文件、qB 任务（含辅种）一起删，腾出空间。删了只能重新下载。',
};

function unwrap(res) {
  if (res && typeof res === 'object' && 'success' in res) {
    if (!res.success) throw new Error(res.message || '请求失败')
    return res.data
  }
  return res
}

function fmtSize(n) {
  n = Number(n) || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`
}
function fmtTime(ts) { return ts ? new Date(ts * 1000).toLocaleString() : '' }
function itemTitle(it) {
  if (it.kind === 'season' && !String(it.title || '').includes(`第 ${it.season} 季`)) return `${it.title} 第 ${it.season} 季`
  return it.title
}
function roleLabel(r) { return r === 'library' ? '库' : r === 'download' ? '下载目录' : '其它' }
function shortPath(p) {
  const s = String(p || '');
  return s.length > 90 ? '…' + s.slice(-88) : s
}

const autoText = computed$1(() => {
  const m = settings.value.watched_auto_mode || 'none';
  if (m === 'none') return '自动删除：关闭（不删）'
  return `自动删除：${MODE_LABELS[m]}，已看满 ${settings.value.watched_buffer_days} 天后执行`
});

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const data = unwrap(await props.api.get(`${props.base}/watched`)) || {};
    items.value = data.items || [];
    meta.value = data.meta || {};
    settings.value = data.settings || {};
    history.value = unwrap(await props.api.get(`${props.base}/watched/history`)) || [];
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}

async function sync() {
  syncing.value = true;
  error.value = '';
  try {
    const out = unwrap(await props.api.post(`${props.base}/watched/sync`, {}));
    notice.value = `已读取极影视：共 ${out.count} 个已看${out.added?.length ? `，新增 ${out.added.length}` : ''}${out.removed?.length ? `，取消 ${out.removed.length}` : ''}`;
    await load();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    syncing.value = false;
  }
}

function openDelete(it, version) {
  target.value = it;
  selected.value = version ? [version.id] : (it.versions || []).filter(v => v.traced).map(v => v.id);
  mode.value = 'library';
  confirmUnknown.value = false;
  plan.value = null;
  result.value = null;
  dialog.value = true;
  preview();
}

// 每次预览一个序号：只认最后一次请求的结果，旧请求晚到时丢掉（否则按钮写的删除方式和实际清单可能不一致）
let previewSeq = 0;

// 换版本或删除方式：要删的文件变了，「确认季号」必须对新清单重新勾选
function selectionChanged() {
  confirmUnknown.value = false;
  preview();
}

async function preview() {
  const seq = ++previewSeq;
  plan.value = null;
  if (!target.value || !selected.value.length) { previewing.value = false; return }
  previewing.value = true;
  error.value = '';
  try {
    const data = unwrap(await props.api.post(`${props.base}/watched/preview`, {
      key: target.value.key, mode: mode.value, version_ids: selected.value,
      confirm_unknown_season: confirmUnknown.value === true,
    }));
    if (seq === previewSeq) plan.value = data;
  } catch (e) {
    if (seq === previewSeq) error.value = e.message || String(e);
  } finally {
    if (seq === previewSeq) previewing.value = false;
  }
}

async function execute() {
  if (!plan.value) return
  executing.value = true;
  try {
    result.value = unwrap(await props.api.post(`${props.base}/watched/execute`, { plan_id: plan.value.id }));
    await load();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    executing.value = false;
  }
}

onMounted$1(load);

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent$1("VAlert");
  const _component_VChip = _resolveComponent$1("VChip");
  const _component_VSpacer = _resolveComponent$1("VSpacer");
  const _component_VBtn = _resolveComponent$1("VBtn");
  const _component_VCardTitle = _resolveComponent$1("VCardTitle");
  const _component_VCardSubtitle = _resolveComponent$1("VCardSubtitle");
  const _component_VCardItem = _resolveComponent$1("VCardItem");
  const _component_VTable = _resolveComponent$1("VTable");
  const _component_VCardText = _resolveComponent$1("VCardText");
  const _component_VCard = _resolveComponent$1("VCard");
  const _component_VCheckbox = _resolveComponent$1("VCheckbox");
  const _component_VRadio = _resolveComponent$1("VRadio");
  const _component_VRadioGroup = _resolveComponent$1("VRadioGroup");
  const _component_VProgressLinear = _resolveComponent$1("VProgressLinear");
  const _component_VCardActions = _resolveComponent$1("VCardActions");
  const _component_VDialog = _resolveComponent$1("VDialog");

  return (_openBlock$1(), _createElementBlock$1("div", null, [
    (error.value)
      ? (_openBlock$1(), _createBlock$1(_component_VAlert, {
          key: 0,
          type: "error",
          variant: "tonal",
          class: "mb-3",
          closable: "",
          "onClick:close": _cache[0] || (_cache[0] = $event => (error.value = ''))
        }, {
          default: _withCtx$1(() => [
            _createTextVNode$1(_toDisplayString$1(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode$1("", true),
    (notice.value)
      ? (_openBlock$1(), _createBlock$1(_component_VAlert, {
          key: 1,
          type: "success",
          variant: "tonal",
          class: "mb-3",
          closable: "",
          "onClick:close": _cache[1] || (_cache[1] = $event => (notice.value = ''))
        }, {
          default: _withCtx$1(() => [
            _createTextVNode$1(_toDisplayString$1(notice.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode$1("", true),
    _createElementVNode$1("div", _hoisted_1$1, [
      _createVNode$1(_component_VChip, {
        variant: "tonal",
        color: (settings.value.watched_auto_mode || 'none') === 'none' ? 'grey' : 'warning'
      }, {
        default: _withCtx$1(() => [
          _createTextVNode$1(_toDisplayString$1(autoText.value), 1)
        ]),
        _: 1
      }, 8, ["color"]),
      _createElementVNode$1("span", _hoisted_2$1, "上次读取 " + _toDisplayString$1(fmtTime(meta.value.last_sync_at) || '—'), 1),
      (meta.value.last_sync_errors?.length)
        ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_3$1, "读取有错：" + _toDisplayString$1(meta.value.last_sync_errors.join('；')), 1))
        : _createCommentVNode$1("", true),
      _createVNode$1(_component_VSpacer),
      _createVNode$1(_component_VBtn, {
        size: "small",
        variant: "tonal",
        "prepend-icon": "mdi-eye-refresh-outline",
        loading: syncing.value,
        onClick: sync
      }, {
        default: _withCtx$1(() => [...(_cache[7] || (_cache[7] = [
          _createTextVNode$1("立即读取已看", -1)
        ]))]),
        _: 1
      }, 8, ["loading"]),
      _createVNode$1(_component_VBtn, {
        size: "small",
        variant: "text",
        icon: "mdi-refresh",
        loading: loading.value,
        "aria-label": "刷新列表",
        onClick: load
      }, null, 8, ["loading"])
    ]),
    _cache[24] || (_cache[24] = _createElementVNode$1("p", { class: "text-caption text-medium-emphasis mb-3" }, " 电影以极影视「已看过」为准；剧集只认对整季点的「已看过」，单集看完不算。库里的入口和下载目录里做种的文件是同一份数据，只移出库不腾空间。 ", -1)),
    (!items.value.length)
      ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_4$1, _toDisplayString$1(loading.value ? '读取中…' : '极影视里还没有标记已看的影片'), 1))
      : _createCommentVNode$1("", true),
    (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(items.value, (it) => {
      return (_openBlock$1(), _createBlock$1(_component_VCard, {
        key: it.key,
        variant: "outlined",
        class: "mb-3"
      }, {
        default: _withCtx$1(() => [
          _createVNode$1(_component_VCardItem, null, {
            append: _withCtx$1(() => [
              _createVNode$1(_component_VBtn, {
                size: "small",
                color: "error",
                variant: "tonal",
                disabled: !(it.versions || []).some(v => v.traced),
                onClick: $event => (openDelete(it))
              }, {
                default: _withCtx$1(() => [...(_cache[8] || (_cache[8] = [
                  _createTextVNode$1("删除…", -1)
                ]))]),
                _: 1
              }, 8, ["disabled", "onClick"])
            ]),
            default: _withCtx$1(() => [
              _createVNode$1(_component_VCardTitle, { class: "text-subtitle-1 d-flex flex-wrap align-center ga-2" }, {
                default: _withCtx$1(() => [
                  _createTextVNode$1(_toDisplayString$1(itemTitle(it)) + " ", 1),
                  (it.year)
                    ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_5$1, "(" + _toDisplayString$1(it.year) + ")", 1))
                    : _createCommentVNode$1("", true),
                  _createVNode$1(_component_VChip, {
                    size: "x-small",
                    variant: "tonal"
                  }, {
                    default: _withCtx$1(() => [
                      _createTextVNode$1(_toDisplayString$1(it.library_name), 1)
                    ]),
                    _: 2
                  }, 1024),
                  (it.done_at)
                    ? (_openBlock$1(), _createBlock$1(_component_VChip, {
                        key: 1,
                        size: "x-small",
                        color: "success",
                        variant: "tonal"
                      }, {
                        default: _withCtx$1(() => [
                          _createTextVNode$1("已处理：" + _toDisplayString$1(MODE_LABELS[it.done_mode]) + " " + _toDisplayString$1(fmtTime(it.done_at)), 1)
                        ]),
                        _: 2
                      }, 1024))
                    : _createCommentVNode$1("", true)
                ]),
                _: 2
              }, 1024),
              _createVNode$1(_component_VCardSubtitle, null, {
                default: _withCtx$1(() => [
                  _createTextVNode$1(" 首次发现已看 " + _toDisplayString$1(fmtTime(it.first_seen_at)) + " ", 1),
                  (!it.done_at)
                    ? (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 0 }, [
                        _createTextVNode$1("· 缓冲期还剩 " + _toDisplayString$1(it.due_in_days) + " 天", 1)
                      ], 64))
                    : _createCommentVNode$1("", true),
                  _createTextVNode$1(" · " + _toDisplayString$1((it.versions || []).length) + " 个版本，共 " + _toDisplayString$1(fmtSize(it.total_size)) + " ", 1),
                  (it.last_error)
                    ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_6$1, " · " + _toDisplayString$1(it.last_error), 1))
                    : _createCommentVNode$1("", true)
                ]),
                _: 2
              }, 1024)
            ]),
            _: 2
          }, 1024),
          _createVNode$1(_component_VCardText, null, {
            default: _withCtx$1(() => [
              (it.error)
                ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_7$1, _toDisplayString$1(it.error), 1))
                : _createCommentVNode$1("", true),
              _createVNode$1(_component_VTable, { density: "compact" }, {
                default: _withCtx$1(() => [
                  _cache[14] || (_cache[14] = _createElementVNode$1("thead", null, [
                    _createElementVNode$1("tr", null, [
                      _createElementVNode$1("th", null, "版本"),
                      _createElementVNode$1("th", null, "大小"),
                      _createElementVNode$1("th", null, "做种"),
                      _createElementVNode$1("th", null, "站点"),
                      _createElementVNode$1("th")
                    ])
                  ], -1)),
                  _createElementVNode$1("tbody", null, [
                    (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(it.versions, (v) => {
                      return (_openBlock$1(), _createElementBlock$1(_Fragment$1, {
                        key: v.id
                      }, [
                        _createElementVNode$1("tr", null, [
                          _createElementVNode$1("td", null, [
                            _createElementVNode$1("a", {
                              href: "#",
                              class: "text-body-2",
                              onClick: _withModifiers($event => (expanded.value[v.id] = !expanded.value[v.id]), ["prevent"])
                            }, _toDisplayString$1(v.label), 9, _hoisted_8$1),
                            (v.in_library)
                              ? (_openBlock$1(), _createBlock$1(_component_VChip, {
                                  key: 0,
                                  size: "x-small",
                                  color: "primary",
                                  variant: "tonal",
                                  class: "ms-1"
                                }, {
                                  default: _withCtx$1(() => [...(_cache[9] || (_cache[9] = [
                                    _createTextVNode$1("库里", -1)
                                  ]))]),
                                  _: 1
                                }))
                              : (_openBlock$1(), _createBlock$1(_component_VChip, {
                                  key: 1,
                                  size: "x-small",
                                  variant: "tonal",
                                  class: "ms-1"
                                }, {
                                  default: _withCtx$1(() => [...(_cache[10] || (_cache[10] = [
                                    _createTextVNode$1("只在下载目录", -1)
                                  ]))]),
                                  _: 1
                                })),
                            (!v.traced)
                              ? (_openBlock$1(), _createBlock$1(_component_VChip, {
                                  key: 2,
                                  size: "x-small",
                                  color: "warning",
                                  variant: "tonal",
                                  class: "ms-1"
                                }, {
                                  default: _withCtx$1(() => [...(_cache[11] || (_cache[11] = [
                                    _createTextVNode$1("记录追溯不到", -1)
                                  ]))]),
                                  _: 1
                                }))
                              : _createCommentVNode$1("", true),
                            (v.season_unknown_count)
                              ? (_openBlock$1(), _createBlock$1(_component_VChip, {
                                  key: 3,
                                  size: "x-small",
                                  color: "warning",
                                  variant: "tonal",
                                  class: "ms-1"
                                }, {
                                  default: _withCtx$1(() => [
                                    _createTextVNode$1(_toDisplayString$1(v.season_unknown_count) + " 个文件认不出季号", 1)
                                  ]),
                                  _: 2
                                }, 1024))
                              : _createCommentVNode$1("", true)
                          ]),
                          _createElementVNode$1("td", null, _toDisplayString$1(v.size_text), 1),
                          _createElementVNode$1("td", null, [
                            (!v.torrents.length)
                              ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_9$1, "无任务"))
                              : (_openBlock$1(), _createElementBlock$1("span", _hoisted_10$1, [
                                  _createTextVNode$1(_toDisplayString$1(v.seeding ? '做种中' : '已停止') + " · " + _toDisplayString$1(v.torrents.length) + " 个任务", 1),
                                  (v.torrents.length > 1)
                                    ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_11$1, "（辅种）"))
                                    : _createCommentVNode$1("", true)
                                ]))
                          ]),
                          _createElementVNode$1("td", _hoisted_12$1, _toDisplayString$1([...new Set([v.site, ...v.torrents.map(t => t.site)].filter(Boolean))].join('、') || '—'), 1),
                          _createElementVNode$1("td", null, [
                            (v.traced)
                              ? (_openBlock$1(), _createBlock$1(_component_VBtn, {
                                  key: 0,
                                  size: "x-small",
                                  variant: "text",
                                  color: "error",
                                  onClick: $event => (openDelete(it, v))
                                }, {
                                  default: _withCtx$1(() => [...(_cache[12] || (_cache[12] = [
                                    _createTextVNode$1("删这个版本", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["onClick"]))
                              : _createCommentVNode$1("", true)
                          ])
                        ]),
                        (expanded.value[v.id])
                          ? (_openBlock$1(), _createElementBlock$1("tr", _hoisted_13$1, [
                              _createElementVNode$1("td", _hoisted_14$1, [
                                (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(v.files, (f) => {
                                  return (_openBlock$1(), _createElementBlock$1("div", {
                                    key: f.path,
                                    class: "text-caption"
                                  }, [
                                    _createVNode$1(_component_VChip, {
                                      size: "x-small",
                                      variant: "outlined",
                                      class: "me-1"
                                    }, {
                                      default: _withCtx$1(() => [
                                        _createTextVNode$1(_toDisplayString$1(roleLabel(f.role)), 1)
                                      ]),
                                      _: 2
                                    }, 1024),
                                    _createElementVNode$1("span", {
                                      class: _normalizeClass({ 'text-disabled': !f.exists })
                                    }, _toDisplayString$1(shortPath(f.path)), 3),
                                    _createTextVNode$1(" · " + _toDisplayString$1(fmtSize(f.size)) + " ", 1),
                                    (f.links && f.links.length > 1)
                                      ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_15$1, " · 同一份数据 " + _toDisplayString$1(f.links.length) + " 个入口", 1))
                                      : _createCommentVNode$1("", true),
                                    (!f.exists)
                                      ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_16$1, " · 已不存在"))
                                      : _createCommentVNode$1("", true),
                                    (f.exists && f.season_unknown)
                                      ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_17$1, " · 认不出季号"))
                                      : _createCommentVNode$1("", true)
                                  ]))
                                }), 128)),
                                (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(v.torrents, (t) => {
                                  return (_openBlock$1(), _createElementBlock$1("div", {
                                    key: t.hash,
                                    class: "text-caption mt-1"
                                  }, [
                                    _createVNode$1(_component_VChip, {
                                      size: "x-small",
                                      variant: "outlined",
                                      class: "me-1"
                                    }, {
                                      default: _withCtx$1(() => [...(_cache[13] || (_cache[13] = [
                                        _createTextVNode$1("qB", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _createTextVNode$1(_toDisplayString$1(t.name) + " · " + _toDisplayString$1(t.site || '?') + " · " + _toDisplayString$1(t.state) + " · " + _toDisplayString$1(t.hash.slice(0, 8)) + " ", 1),
                                    (t.foreign_media?.length)
                                      ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_18$1, " · 种子里还有 " + _toDisplayString$1(t.foreign_media.length) + " 个别的视频", 1))
                                      : _createCommentVNode$1("", true)
                                  ]))
                                }), 128)),
                                (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(v.notes, (n) => {
                                  return (_openBlock$1(), _createElementBlock$1("div", {
                                    key: n,
                                    class: "text-caption text-medium-emphasis"
                                  }, _toDisplayString$1(n), 1))
                                }), 128))
                              ])
                            ]))
                          : _createCommentVNode$1("", true)
                      ], 64))
                    }), 128))
                  ])
                ]),
                _: 2
              }, 1024)
            ]),
            _: 2
          }, 1024)
        ]),
        _: 2
      }, 1024))
    }), 128)),
    (history.value.length)
      ? (_openBlock$1(), _createBlock$1(_component_VCard, {
          key: 3,
          variant: "outlined",
          class: "mt-4"
        }, {
          default: _withCtx$1(() => [
            _createVNode$1(_component_VCardTitle, { class: "text-subtitle-1" }, {
              default: _withCtx$1(() => [...(_cache[15] || (_cache[15] = [
                _createTextVNode$1("删除记录", -1)
              ]))]),
              _: 1
            }),
            _createVNode$1(_component_VCardText, null, {
              default: _withCtx$1(() => [
                _createVNode$1(_component_VTable, { density: "compact" }, {
                  default: _withCtx$1(() => [
                    _cache[16] || (_cache[16] = _createElementVNode$1("thead", null, [
                      _createElementVNode$1("tr", null, [
                        _createElementVNode$1("th", null, "时间"),
                        _createElementVNode$1("th", null, "影片"),
                        _createElementVNode$1("th", null, "方式"),
                        _createElementVNode$1("th", null, "结果")
                      ])
                    ], -1)),
                    _createElementVNode$1("tbody", null, [
                      (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(history.value.slice(0, 30), (h) => {
                        return (_openBlock$1(), _createElementBlock$1("tr", {
                          key: h.plan_id + h.started_at
                        }, [
                          _createElementVNode$1("td", _hoisted_19$1, _toDisplayString$1(fmtTime(h.started_at)), 1),
                          _createElementVNode$1("td", null, _toDisplayString$1(h.title), 1),
                          _createElementVNode$1("td", _hoisted_20$1, _toDisplayString$1(h.mode_label) + "（" + _toDisplayString$1(h.trigger === 'auto' ? '自动' : '手动') + "）", 1),
                          _createElementVNode$1("td", _hoisted_21$1, [
                            _createTextVNode$1(_toDisplayString$1(h.status === 'done' ? '完成' : h.status === 'aborted' ? '未执行' : '部分失败') + "：删 " + _toDisplayString$1((h.deleted || []).length) + " 个文件", 1),
                            ((h.torrents_removed || []).length)
                              ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_22$1, "、" + _toDisplayString$1(h.torrents_removed.length) + " 个种子", 1))
                              : _createCommentVNode$1("", true),
                            _createTextVNode$1("，腾出 " + _toDisplayString$1(h.freed_text) + " ", 1),
                            ((h.failed || []).length)
                              ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_23, _toDisplayString$1(h.failed.join('；')), 1))
                              : _createCommentVNode$1("", true)
                          ])
                        ]))
                      }), 128))
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode$1("", true),
    _createVNode$1(_component_VDialog, {
      modelValue: dialog.value,
      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((dialog).value = $event)),
      "max-width": "900",
      scrollable: ""
    }, {
      default: _withCtx$1(() => [
        (target.value)
          ? (_openBlock$1(), _createBlock$1(_component_VCard, { key: 0 }, {
              default: _withCtx$1(() => [
                _createVNode$1(_component_VCardTitle, null, {
                  default: _withCtx$1(() => [
                    _createTextVNode$1("删除：" + _toDisplayString$1(itemTitle(target.value)), 1)
                  ]),
                  _: 1
                }),
                _createVNode$1(_component_VCardText, null, {
                  default: _withCtx$1(() => [
                    _cache[22] || (_cache[22] = _createElementVNode$1("div", { class: "mb-2 text-subtitle-2" }, "选版本", -1)),
                    (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(target.value.versions.filter(x => x.traced), (v) => {
                      return (_openBlock$1(), _createBlock$1(_component_VCheckbox, {
                        key: v.id,
                        modelValue: selected.value,
                        "onUpdate:modelValue": [
                          _cache[2] || (_cache[2] = $event => ((selected).value = $event)),
                          selectionChanged
                        ],
                        value: v.id,
                        density: "compact",
                        "hide-details": "",
                        disabled: !!result.value
                      }, {
                        label: _withCtx$1(() => [
                          _createTextVNode$1(_toDisplayString$1(v.label) + "（" + _toDisplayString$1(v.size_text) + _toDisplayString$1(v.in_library ? '，库里' : '，只在下载目录') + "）", 1)
                        ]),
                        _: 2
                      }, 1032, ["modelValue", "value", "disabled"]))
                    }), 128)),
                    _cache[23] || (_cache[23] = _createElementVNode$1("div", { class: "mt-3 mb-1 text-subtitle-2" }, "删除方式", -1)),
                    _createVNode$1(_component_VRadioGroup, {
                      modelValue: mode.value,
                      "onUpdate:modelValue": [
                        _cache[3] || (_cache[3] = $event => ((mode).value = $event)),
                        selectionChanged
                      ],
                      inline: "",
                      "hide-details": "",
                      disabled: !!result.value
                    }, {
                      default: _withCtx$1(() => [
                        _createVNode$1(_component_VRadio, {
                          label: "只从库里移除",
                          value: "library"
                        }),
                        _createVNode$1(_component_VRadio, {
                          label: "真删除（含做种）",
                          value: "full",
                          color: "error"
                        })
                      ]),
                      _: 1
                    }, 8, ["modelValue", "disabled"]),
                    _createElementVNode$1("p", _hoisted_24, _toDisplayString$1(MODE_HINTS[mode.value]), 1),
                    (previewing.value)
                      ? (_openBlock$1(), _createBlock$1(_component_VProgressLinear, {
                          key: 0,
                          indeterminate: "",
                          class: "mb-2"
                        }))
                      : _createCommentVNode$1("", true),
                    (plan.value && !result.value)
                      ? (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 1 }, [
                          _createVNode$1(_component_VAlert, {
                            type: plan.value.freed_bytes ? 'warning' : 'info',
                            variant: "tonal",
                            class: "mb-2"
                          }, {
                            default: _withCtx$1(() => [
                              _createTextVNode$1(" 将删除 " + _toDisplayString$1(plan.value.actions.length) + " 个文件", 1),
                              (plan.value.torrents.length)
                                ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_25, "、" + _toDisplayString$1(plan.value.torrents.length) + " 个 qB 任务", 1))
                                : _createCommentVNode$1("", true),
                              _cache[17] || (_cache[17] = _createTextVNode$1("， 腾出 ", -1)),
                              _createElementVNode$1("b", null, _toDisplayString$1(plan.value.freed_text), 1)
                            ]),
                            _: 1
                          }, 8, ["type"]),
                          (plan.value.unknown_season && plan.value.unknown_season.count)
                            ? (_openBlock$1(), _createBlock$1(_component_VAlert, {
                                key: 0,
                                type: "warning",
                                variant: "outlined",
                                density: "compact",
                                class: "mb-2"
                              }, {
                                default: _withCtx$1(() => [
                                  _createElementVNode$1("div", null, [
                                    _cache[18] || (_cache[18] = _createTextVNode$1(" 有 ", -1)),
                                    _createElementVNode$1("b", null, _toDisplayString$1(plan.value.unknown_season.count), 1),
                                    _createTextVNode$1(" 个文件（" + _toDisplayString$1(plan.value.unknown_season.size_text) + "）路径里认不出季号（蓝光原盘之类）， ", 1),
                                    (plan.value.unknown_season.confirmed)
                                      ? (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 0 }, [
                                          _createTextVNode$1("已按你的确认纳入这次删除。")
                                        ], 64))
                                      : (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 1 }, [
                                          _createTextVNode$1(_toDisplayString$1(mode.value === 'full' ? '这些文件所在的版本连同种子这次都不删' : '这些库入口这次不移出') + "。", 1)
                                        ], 64))
                                  ]),
                                  (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(plan.value.unknown_season.dirs, (d) => {
                                    return (_openBlock$1(), _createElementBlock$1("div", {
                                      key: d.dir,
                                      class: "text-caption"
                                    }, "· " + _toDisplayString$1(shortPath(d.dir)) + "：" + _toDisplayString$1(d.count) + " 个，" + _toDisplayString$1(d.size_text), 1))
                                  }), 128)),
                                  _createVNode$1(_component_VCheckbox, {
                                    modelValue: confirmUnknown.value,
                                    "onUpdate:modelValue": [
                                      _cache[4] || (_cache[4] = $event => ((confirmUnknown).value = $event)),
                                      preview
                                    ],
                                    density: "compact",
                                    "hide-details": "",
                                    color: "error",
                                    disabled: !!result.value
                                  }, {
                                    label: _withCtx$1(() => [
                                      _createTextVNode$1("我确认这些文件属于第 " + _toDisplayString$1(plan.value.unknown_season.season) + " 季，一起" + _toDisplayString$1(mode.value === 'full' ? '删除' : '移出库'), 1)
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue", "disabled"]),
                                  _cache[19] || (_cache[19] = _createElementVNode$1("div", { class: "text-caption text-medium-emphasis" }, "自动删除永远不会删这类文件，只能在这里手动确认。", -1))
                                ]),
                                _: 1
                              }))
                            : _createCommentVNode$1("", true),
                          (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(plan.value.warnings, (w) => {
                            return (_openBlock$1(), _createElementBlock$1("div", {
                              key: w,
                              class: "text-caption text-warning"
                            }, "· " + _toDisplayString$1(w), 1))
                          }), 128)),
                          (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(plan.value.skipped, (w) => {
                            return (_openBlock$1(), _createElementBlock$1("div", {
                              key: w,
                              class: "text-caption text-medium-emphasis"
                            }, "· 跳过：" + _toDisplayString$1(w), 1))
                          }), 128)),
                          _cache[21] || (_cache[21] = _createElementVNode$1("div", { class: "mt-2 text-subtitle-2" }, "文件", -1)),
                          (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(plan.value.actions, (a) => {
                            return (_openBlock$1(), _createElementBlock$1("div", {
                              key: a.path,
                              class: "text-caption"
                            }, [
                              _createVNode$1(_component_VChip, {
                                size: "x-small",
                                variant: "outlined",
                                class: "me-1"
                              }, {
                                default: _withCtx$1(() => [
                                  _createTextVNode$1(_toDisplayString$1(roleLabel(a.role)), 1)
                                ]),
                                _: 2
                              }, 1024),
                              _createTextVNode$1(_toDisplayString$1(shortPath(a.path)) + " · " + _toDisplayString$1(fmtSize(a.size)) + " ", 1),
                              (a.nlink > 1)
                                ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_26, " · " + _toDisplayString$1(a.nlink) + " 个入口", 1))
                                : _createCommentVNode$1("", true)
                            ]))
                          }), 128)),
                          (plan.value.torrents.length)
                            ? (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 1 }, [
                                _cache[20] || (_cache[20] = _createElementVNode$1("div", { class: "mt-2 text-subtitle-2" }, "qB 任务（连同文件删除）", -1)),
                                (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(plan.value.torrents, (t) => {
                                  return (_openBlock$1(), _createElementBlock$1("div", {
                                    key: t.hash,
                                    class: "text-caption"
                                  }, _toDisplayString$1(t.site || '?') + " · " + _toDisplayString$1(t.name) + " · " + _toDisplayString$1(t.hash.slice(0, 8)), 1))
                                }), 128))
                              ], 64))
                            : _createCommentVNode$1("", true)
                        ], 64))
                      : _createCommentVNode$1("", true),
                    (result.value)
                      ? (_openBlock$1(), _createElementBlock$1(_Fragment$1, { key: 2 }, [
                          _createVNode$1(_component_VAlert, {
                            type: result.value.status === 'done' ? 'success' : 'error',
                            variant: "tonal",
                            class: "mb-2"
                          }, {
                            default: _withCtx$1(() => [
                              _createTextVNode$1(_toDisplayString$1(result.value.status === 'done' ? '完成' : result.value.status === 'aborted' ? '没有执行' : '部分失败') + "： 删了 " + _toDisplayString$1(result.value.deleted.length) + " 个文件", 1),
                              (result.value.torrents_removed.length)
                                ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_27, "、" + _toDisplayString$1(result.value.torrents_removed.length) + " 个种子", 1))
                                : _createCommentVNode$1("", true),
                              _createTextVNode$1("，腾出 " + _toDisplayString$1(result.value.freed_text), 1)
                            ]),
                            _: 1
                          }, 8, ["type"]),
                          (_openBlock$1(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(result.value.failed, (f) => {
                            return (_openBlock$1(), _createElementBlock$1("div", {
                              key: f,
                              class: "text-caption text-error"
                            }, "· " + _toDisplayString$1(f), 1))
                          }), 128)),
                          (result.value.zvideo)
                            ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_28, " 极影视：已刷新 " + _toDisplayString$1((result.value.zvideo.rescan_targets || []).length) + " 个目录； " + _toDisplayString$1((result.value.zvideo.still_in_zvideo || []).length ? `还看得到 ${result.value.zvideo.still_in_zvideo.length} 个已删文件` : '已删的文件已不在条目里'), 1))
                            : _createCommentVNode$1("", true)
                        ], 64))
                      : _createCommentVNode$1("", true)
                  ]),
                  _: 1
                }),
                _createVNode$1(_component_VCardActions, null, {
                  default: _withCtx$1(() => [
                    _createVNode$1(_component_VSpacer),
                    _createVNode$1(_component_VBtn, {
                      variant: "text",
                      onClick: _cache[5] || (_cache[5] = $event => (dialog.value = false))
                    }, {
                      default: _withCtx$1(() => [
                        _createTextVNode$1(_toDisplayString$1(result.value ? '关闭' : '取消'), 1)
                      ]),
                      _: 1
                    }),
                    (!result.value)
                      ? (_openBlock$1(), _createBlock$1(_component_VBtn, {
                          key: 0,
                          color: "error",
                          variant: "flat",
                          loading: executing.value,
                          disabled: !plan.value || previewing.value || (!plan.value.actions.length && !plan.value.torrents.length),
                          onClick: execute
                        }, {
                          default: _withCtx$1(() => [
                            _createTextVNode$1(" 确认" + _toDisplayString$1(mode.value === 'full' ? '真删除' : '移出库'), 1)
                          ]),
                          _: 1
                        }, 8, ["loading", "disabled"]))
                      : _createCommentVNode$1("", true)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : _createCommentVNode$1("", true)
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,withKeys:_withKeys,renderList:_renderList,Fragment:_Fragment,vShow:_vShow,withDirectives:_withDirectives} = await importShared('vue');


const _hoisted_1 = { class: "zsv-page" };
const _hoisted_2 = {
  key: 0,
  class: "pa-4"
};
const _hoisted_3 = {
  key: 0,
  class: "text-medium-emphasis"
};
const _hoisted_4 = { class: "pa-4" };
const _hoisted_5 = { class: "d-flex flex-wrap ga-4 align-center mb-2" };
const _hoisted_6 = { key: 0 };
const _hoisted_7 = { key: 1 };
const _hoisted_8 = { key: 2 };
const _hoisted_9 = {
  key: 0,
  class: "d-flex ga-2"
};
const _hoisted_10 = { key: 1 };
const _hoisted_11 = { class: "mb-2" };
const _hoisted_12 = { class: "mb-3" };
const _hoisted_13 = ["href"];
const _hoisted_14 = { class: "d-flex ga-2 align-center" };
const _hoisted_15 = { class: "text-caption ms-2" };
const _hoisted_16 = {
  key: 0,
  class: "text-medium-emphasis"
};
const _hoisted_17 = {
  key: 0,
  class: "text-caption"
};
const _hoisted_18 = {
  key: 0,
  class: "text-caption text-warning"
};
const _hoisted_19 = {
  key: 0,
  class: "text-medium-emphasis"
};
const _hoisted_20 = { class: "text-caption" };
const _hoisted_21 = { class: "text-caption" };
const _hoisted_22 = {
  key: 0,
  class: "text-caption text-error"
};

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'ZSpaceVideo' },
  show_switch: { type: Boolean, default: true },
},
  emits: ['close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const base = computed(() => `plugin/${props.pluginId || 'ZSpaceVideo'}`);

const status = ref({});
const libraries = ref([]);
const librarySource = ref('');
const history = ref([]);
const loading = ref(false);
const error = ref('');
const notice = ref('');
const login = ref({ url: '', expires_in: 0, started: 0 });
const code = ref('');
const submitting = ref(false);
const now = ref(Date.now());
let timer = null;
const tab = ref('watched');

function unwrap(res) {
  if (res && typeof res === 'object' && 'success' in res) {
    if (!res.success) throw new Error(res.message || '请求失败')
    return res.data
  }
  return res
}

const remaining = computed(() => {
  if (!login.value.url) return 0
  const left = login.value.expires_in - Math.floor((now.value - login.value.started) / 1000);
  return Math.max(0, left)
});

const expiresText = computed(() => {
  const ts = status.value.expires_at;
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
});

const statusLabel = { pending: '排队', running: '扫描中', done: '完成', failed: '失败' };
const statusColor = { pending: 'grey', running: 'info', done: 'success', failed: 'error' };

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

async function loadStatus() {
  status.value = unwrap(await props.api.get(`${base.value}/status`)) || {};
}
async function loadLibraries(force = false) {
  const data = unwrap(await props.api.get(`${base.value}/libraries`, { params: { force } })) || {};
  libraries.value = data.libraries || [];
  librarySource.value = data.source || '';
}
async function loadHistory() {
  history.value = unwrap(await props.api.get(`${base.value}/history`)) || [];
}

async function reload(force = false) {
  loading.value = true;
  error.value = '';
  try {
    await loadStatus();
    await loadHistory();
    if (status.value.logged_in) await loadLibraries(force);
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}

async function startLogin() {
  error.value = '';
  notice.value = '';
  code.value = '';
  try {
    const data = unwrap(await props.api.post(`${base.value}/login/start`, {}));
    login.value = { url: data.url, expires_in: data.expires_in || 180, started: Date.now() };
  } catch (e) {
    error.value = e.message || String(e);
  }
}

async function submitCode() {
  if (!code.value.trim()) return
  submitting.value = true;
  error.value = '';
  try {
    const payload = { code: code.value.trim() };
    code.value = '';
    unwrap(await props.api.post(`${base.value}/login/submit`, payload));
    payload.code = '';
    login.value = { url: '', expires_in: 0, started: 0 };
    notice.value = '授权成功';
    await reload(true);
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    submitting.value = false;
  }
}

async function cancelLogin() {
  await props.api.post(`${base.value}/login/cancel`, {});
  login.value = { url: '', expires_in: 0, started: 0 };
  code.value = '';
}

async function logout() {
  if (!confirm('清除本插件保存的极空间授权？')) return
  try {
    unwrap(await props.api.post(`${base.value}/logout`, {}));
    notice.value = '已清除本地授权';
    await reload();
  } catch (e) {
    error.value = e.message || String(e);
  }
}

async function refreshLibrary(lib) {
  error.value = '';
  try {
    unwrap(await props.api.post(`${base.value}/refresh`, { library_id: lib.id }));
    notice.value = `已提交刷新：${lib.name}`;
    setTimeout(loadHistory, 1500);
  } catch (e) {
    error.value = e.message || String(e);
  }
}

onMounted(() => {
  reload();
  timer = setInterval(() => {
    now.value = Date.now();
    if (now.value % 10000 < 1000) loadHistory().catch(() => {});
  }, 1000);
});
onUnmounted(() => timer && clearInterval(timer));

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VTab = _resolveComponent("VTab");
  const _component_VTabs = _resolveComponent("VTabs");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VTable = _resolveComponent("VTable");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      class: "zsv-toolbar"
    }, {
      default: _withCtx(() => [
        _cache[7] || (_cache[7] = _createElementVNode("div", { class: "text-h6 ms-3" }, "极空间影视", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-refresh",
          variant: "text",
          loading: loading.value,
          "aria-label": "刷新",
          onClick: _cache[0] || (_cache[0] = $event => (reload(true)))
        }, null, 8, ["loading"]),
        (props.show_switch)
          ? (_openBlock(), _createBlock(_component_VBtn, {
              key: 0,
              icon: "mdi-cog-outline",
              variant: "text",
              "aria-label": "插件设置",
              onClick: _cache[1] || (_cache[1] = $event => (emit('switch')))
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          "aria-label": "关闭",
          onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createVNode(_component_VTabs, {
      modelValue: tab.value,
      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((tab).value = $event)),
      density: "comfortable",
      class: "px-2"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VTab, { value: "watched" }, {
          default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
            _createTextVNode("已看", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VTab, { value: "refresh" }, {
          default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
            _createTextVNode("授权与刷新", -1)
          ]))]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VDivider),
    (tab.value === 'watched')
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, [
          (!status.value.logged_in && !loading.value)
            ? (_openBlock(), _createElementBlock("div", _hoisted_3, "先在「授权与刷新」里完成极空间授权"))
            : (_openBlock(), _createBlock(_sfc_main$1, {
                key: 1,
                api: props.api,
                base: base.value
              }, null, 8, ["api", "base"]))
        ]))
      : _createCommentVNode("", true),
    _withDirectives(_createElementVNode("div", _hoisted_4, [
      (error.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: "error",
            variant: "tonal",
            class: "mb-3",
            closable: "",
            "onClick:close": _cache[4] || (_cache[4] = $event => (error.value = ''))
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(error.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (notice.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 1,
            type: "success",
            variant: "tonal",
            class: "mb-3",
            closable: "",
            "onClick:close": _cache[5] || (_cache[5] = $event => (notice.value = ''))
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(notice.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "mb-4"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
            default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
              _createTextVNode("授权", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createElementVNode("div", _hoisted_5, [
                _createVNode(_component_VChip, {
                  color: status.value.logged_in ? 'success' : 'warning',
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(status.value.logged_in ? '已授权' : '未授权'), 1)
                  ]),
                  _: 1
                }, 8, ["color"]),
                (status.value.nas_id)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_6, "设备 " + _toDisplayString(status.value.nas_id), 1))
                  : _createCommentVNode("", true),
                (status.value.logged_in)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_7, "令牌到期 " + _toDisplayString(expiresText.value) + "（到期前自动续期）", 1))
                  : _createCommentVNode("", true),
                _createElementVNode("span", null, "连接：" + _toDisplayString(status.value.connection_mode === 'lan' ? '局域网直连' : '官方云中转'), 1),
                (status.value.binary)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_8, "zspace-cli " + _toDisplayString(status.value.binary.version) + _toDisplayString(status.value.binary.installed ? '' : '（未下载）'), 1))
                  : _createCommentVNode("", true)
              ]),
              (!login.value.url)
                ? (_openBlock(), _createElementBlock("div", _hoisted_9, [
                    _createVNode(_component_VBtn, {
                      color: "primary",
                      "prepend-icon": "mdi-shield-key-outline",
                      onClick: startLogin
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(status.value.logged_in ? '重新授权' : '开始授权'), 1)
                      ]),
                      _: 1
                    }),
                    (status.value.logged_in)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 0,
                          variant: "text",
                          color: "error",
                          onClick: logout
                        }, {
                          default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                            _createTextVNode("清除授权", -1)
                          ]))]),
                          _: 1
                        }))
                      : _createCommentVNode("", true)
                  ]))
                : (_openBlock(), _createElementBlock("div", _hoisted_10, [
                    _createElementVNode("p", _hoisted_11, [
                      _cache[12] || (_cache[12] = _createTextVNode(" 打开下面的链接，用极空间账号登录并同意授权，然后把页面上显示的一次性授权码粘贴回来。 剩余 ", -1)),
                      _createElementVNode("b", null, _toDisplayString(remaining.value), 1),
                      _cache[13] || (_cache[13] = _createTextVNode(" 秒，超时请重新开始。 ", -1))
                    ]),
                    _createElementVNode("p", _hoisted_12, [
                      _createElementVNode("a", {
                        href: login.value.url,
                        target: "_blank",
                        rel: "noopener noreferrer"
                      }, "打开极空间授权页面", 8, _hoisted_13)
                    ]),
                    _createElementVNode("div", _hoisted_14, [
                      _createVNode(_component_VTextField, {
                        modelValue: code.value,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((code).value = $event)),
                        label: "一次性授权码",
                        type: "password",
                        autocomplete: "off",
                        density: "comfortable",
                        "hide-details": "",
                        disabled: remaining.value === 0,
                        onKeyup: _withKeys(submitCode, ["enter"])
                      }, null, 8, ["modelValue", "disabled"]),
                      _createVNode(_component_VBtn, {
                        color: "primary",
                        loading: submitting.value,
                        disabled: !code.value || remaining.value === 0,
                        onClick: submitCode
                      }, {
                        default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                          _createTextVNode("提交", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading", "disabled"]),
                      _createVNode(_component_VBtn, {
                        variant: "text",
                        onClick: cancelLogin
                      }, {
                        default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                          _createTextVNode("取消", -1)
                        ]))]),
                        _: 1
                      })
                    ])
                  ]))
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "mb-4"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
            default: _withCtx(() => [
              _cache[16] || (_cache[16] = _createTextVNode(" 分类 ", -1)),
              _createElementVNode("span", _hoisted_15, "目录来源：" + _toDisplayString(librarySource.value === 'zvideo.db' ? '极影视库（只读）' : librarySource.value === 'manual' ? '手动配置' : '无'), 1)
            ]),
            _: 1
          }),
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              (!status.value.logged_in)
                ? (_openBlock(), _createElementBlock("div", _hoisted_16, "授权后显示"))
                : (_openBlock(), _createBlock(_component_VTable, {
                    key: 1,
                    density: "compact"
                  }, {
                    default: _withCtx(() => [
                      _cache[18] || (_cache[18] = _createElementVNode("thead", null, [
                        _createElementVNode("tr", null, [
                          _createElementVNode("th", null, "分类"),
                          _createElementVNode("th", null, "目录"),
                          _createElementVNode("th", null, "状态"),
                          _createElementVNode("th")
                        ])
                      ], -1)),
                      _createElementVNode("tbody", null, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(libraries.value, (lib) => {
                          return (_openBlock(), _createElementBlock("tr", {
                            key: lib.id
                          }, [
                            _createElementVNode("td", null, [
                              _createTextVNode(_toDisplayString(lib.name), 1),
                              (lib.is_system)
                                ? (_openBlock(), _createElementBlock("span", _hoisted_17, " · 智能"))
                                : _createCommentVNode("", true)
                            ]),
                            _createElementVNode("td", null, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(lib.dirs, (d) => {
                                return (_openBlock(), _createElementBlock("div", {
                                  key: d,
                                  class: "text-caption"
                                }, _toDisplayString(d), 1))
                              }), 128)),
                              (!lib.dirs.length)
                                ? (_openBlock(), _createElementBlock("span", _hoisted_18, "未知目录，不会自动刷新"))
                                : _createCommentVNode("", true)
                            ]),
                            _createElementVNode("td", null, _toDisplayString(lib.scan_status === 0 ? '空闲' : lib.scan_status == null ? '—' : '扫描中'), 1),
                            _createElementVNode("td", null, [
                              _createVNode(_component_VBtn, {
                                size: "small",
                                variant: "tonal",
                                disabled: !lib.dirs.length,
                                onClick: $event => (refreshLibrary(lib))
                              }, {
                                default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                                  _createTextVNode("立即刷新", -1)
                                ]))]),
                                _: 1
                              }, 8, ["disabled", "onClick"])
                            ])
                          ]))
                        }), 128))
                      ])
                    ]),
                    _: 1
                  }))
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, { variant: "outlined" }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
            default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
              _createTextVNode("最近刷新", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              (!history.value.length)
                ? (_openBlock(), _createElementBlock("div", _hoisted_19, "还没有记录"))
                : (_openBlock(), _createBlock(_component_VTable, {
                    key: 1,
                    density: "compact"
                  }, {
                    default: _withCtx(() => [
                      _cache[20] || (_cache[20] = _createElementVNode("thead", null, [
                        _createElementVNode("tr", null, [
                          _createElementVNode("th", null, "时间"),
                          _createElementVNode("th", null, "来源"),
                          _createElementVNode("th", null, "分类"),
                          _createElementVNode("th", null, "目录"),
                          _createElementVNode("th", null, "结果")
                        ])
                      ], -1)),
                      _createElementVNode("tbody", null, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(history.value.slice(0, 50), (h) => {
                          return (_openBlock(), _createElementBlock("tr", {
                            key: h.id
                          }, [
                            _createElementVNode("td", _hoisted_20, _toDisplayString(fmtTime(h.created_at)), 1),
                            _createElementVNode("td", _hoisted_21, _toDisplayString(h.trigger === 'manual' ? '手动' : (h.sources || []).join('、') || '整理'), 1),
                            _createElementVNode("td", null, _toDisplayString(h.library_name), 1),
                            _createElementVNode("td", null, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(h.paths, (p) => {
                                return (_openBlock(), _createElementBlock("div", {
                                  key: p,
                                  class: "text-caption"
                                }, _toDisplayString(p), 1))
                              }), 128))
                            ]),
                            _createElementVNode("td", null, [
                              _createVNode(_component_VChip, {
                                size: "small",
                                color: statusColor[h.status],
                                variant: "tonal"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode(_toDisplayString(statusLabel[h.status] || h.status), 1)
                                ]),
                                _: 2
                              }, 1032, ["color"]),
                              (h.status === 'failed')
                                ? (_openBlock(), _createElementBlock("div", _hoisted_22, _toDisplayString(h.message), 1))
                                : _createCommentVNode("", true)
                            ])
                          ]))
                        }), 128))
                      ])
                    ]),
                    _: 1
                  }))
            ]),
            _: 1
          })
        ]),
        _: 1
      })
    ], 512), [
      [_vShow, tab.value === 'refresh']
    ])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-8caf847b"]]);

export { Page as default };
