import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

/**
 * MoviePilot 的联邦页面在不同宿主版本会多包一层或两层 data。
 * 业务代码只接受最终负载；失败响应始终原样抛出，不能被误当成空数据。
 */
function unwrapMoviePilotResponse (value) {
  let current = value;
  const seen = new Set();
  for (let depth = 0; depth < 6 && current && typeof current === 'object'; depth += 1) {
    if (seen.has(current)) break
    seen.add(current);
    if (current.success === false) throw new Error(current.message || 'MoviePilot 请求失败')
    if (!Object.prototype.hasOwnProperty.call(current, 'data') || current.data === undefined) break
    current = current.data;
  }
  return current
}

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,normalizeStyle:_normalizeStyle,renderList:_renderList,Fragment:_Fragment,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "governor-shell" };
const _hoisted_2 = { class: "hero" };
const _hoisted_3 = { class: "actions" };
const _hoisted_4 = ["disabled"];
const _hoisted_5 = { class: "advanced" };
const _hoisted_6 = ["disabled"];
const _hoisted_7 = {
  class: "status-card",
  "aria-live": "polite"
};
const _hoisted_8 = { class: "status-line" };
const _hoisted_9 = {
  key: 0,
  class: "bar"
};
const _hoisted_10 = {
  key: 1,
  class: "warning"
};
const _hoisted_11 = {
  key: 2,
  class: "notice"
};
const _hoisted_12 = { class: "summary-grid" };
const _hoisted_13 = { class: "panel" };
const _hoisted_14 = ["onClick"];
const _hoisted_15 = {
  key: 0,
  class: "empty"
};
const _hoisted_16 = { class: "panel review-panel" };
const _hoisted_17 = ["onClick"];
const _hoisted_18 = {
  key: 0,
  class: "empty"
};
const _hoisted_19 = { class: "panel error-panel" };
const _hoisted_20 = ["onClick"];
const _hoisted_21 = {
  key: 0,
  class: "empty"
};
const _hoisted_22 = ["aria-label"];
const _hoisted_23 = { class: "lead small" };
const _hoisted_24 = { class: "facts" };
const _hoisted_25 = {
  key: 0,
  class: "choice-area"
};
const _hoisted_26 = {
  key: 0,
  class: "warning"
};
const _hoisted_27 = ["disabled", "onClick"];
const _hoisted_28 = {
  key: 1,
  class: "choice-area"
};
const _hoisted_29 = ["disabled"];
const _hoisted_30 = {
  key: 2,
  class: "preview"
};
const _hoisted_31 = {
  key: 1,
  class: "final-confirm"
};
const _hoisted_32 = ["disabled"];

const {computed,onBeforeUnmount,onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'AppPage',
  props: { api: { type: Object, default: () => ({}) } },
  setup(__props) {

const props = __props;
const snapshot = ref({ status: { job: { status: 'idle', phase: 'IDLE', total: 0, done: 0, current: '尚未检查', error: '' }, counts: {}, objects: 0 }, problems: [], confirmations: [], errors: [] });
const busy = ref(false);
const message = ref('');
const selected = ref(null);
const repairPlan = ref(null);
const confirmingRepair = ref(false);
let timer = null;

const job = computed(() => snapshot.value.status?.job || {});
const running = computed(() => job.value.status === 'running');
const progress = computed(() => job.value.total ? Math.round((job.value.done || 0) * 100 / job.value.total) : 0);
const hasResults = computed(() => snapshot.value.problems.length + snapshot.value.confirmations.length + snapshot.value.errors.length > 0);

function failure (error, fallback) {
  message.value = error?.message || fallback;
}

async function get (path) {
  return unwrapMoviePilotResponse(await props.api.get(path, { feedback: 'silent' }))
}

async function post (path, body) {
  return unwrapMoviePilotResponse(await props.api.post(path, body, { feedback: 'silent' }))
}

async function refresh () {
  try {
    snapshot.value = await get('plugin/MediaGovernor/findings');
  } catch (error) {
    failure(error, '没有读到媒体治理状态');
  }
}

async function start (mode) {
  busy.value = true;
  message.value = mode === 'full' ? '正在重新建立完整基线。' : '正在检查当前变动。';
  try {
    await post('plugin/MediaGovernor/audit/start', { mode });
    await refresh();
  } catch (error) {
    failure(error, '没有启动检查');
  } finally {
    busy.value = false;
  }
}

async function cancel () {
  try {
    await post('plugin/MediaGovernor/audit/start', { mode: 'cancel' });
    await refresh();
  } catch (error) {
    failure(error, '没有提交停止请求');
  }
}

async function openItem (item) {
  busy.value = true;
  message.value = '';
  repairPlan.value = null;
  confirmingRepair.value = false;
  try {
    selected.value = await get(`plugin/MediaGovernor/objects/${encodeURIComponent(item.object_id)}`);
    selected.value.finding = item;
  } catch (error) {
    failure(error, '没有读到这部作品的证据');
  } finally {
    busy.value = false;
  }
}

function candidateKey (candidate) {
  const source = ['tmdb', 'the_movie_db'].includes(String(candidate?.media_source || '').toLowerCase()) ? 'themoviedb' : String(candidate?.media_source || '').toLowerCase();
  return `${source}:${candidate?.media_id || ''}:${candidate?.media_type || 'unknown'}`
}

async function confirmIdentity (candidate) {
  if (!selected.value) return
  busy.value = true;
  try {
    await post('plugin/MediaGovernor/identity/confirm', { object_id: selected.value.id, candidate_key: candidateKey(candidate) });
    message.value = '身份已保存，只重新核对这一部作品。';
    selected.value = null;
    await refresh();
  } catch (error) {
    failure(error, '没有保存作品身份');
  } finally {
    busy.value = false;
  }
}

async function previewRepair () {
  if (!selected.value) return
  busy.value = true;
  try {
    repairPlan.value = await post(`plugin/MediaGovernor/repair/${encodeURIComponent(selected.value.id)}`, { action: 'preview' });
    confirmingRepair.value = false;
  } catch (error) {
    failure(error, '没有生成当前修复预览');
  } finally {
    busy.value = false;
  }
}

async function executeRepair () {
  if (!selected.value || !repairPlan.value?.token) return
  busy.value = true;
  try {
    const result = await post(`plugin/MediaGovernor/repair/${encodeURIComponent(selected.value.id)}`, { action: 'execute', token: repairPlan.value.token });
    message.value = result.message || 'MoviePilot 已完成重建，正在复核。';
    selected.value = null;
    repairPlan.value = null;
    await refresh();
  } catch (error) {
    failure(error, 'MoviePilot 没有完成重建');
  } finally {
    busy.value = false;
  }
}

function closeDetail () {
  selected.value = null;
  repairPlan.value = null;
  confirmingRepair.value = false;
}

onMounted(async () => {
  await refresh();
  timer = window.setInterval(() => { if (running.value) refresh(); }, 1500);
});
onBeforeUnmount(() => window.clearInterval(timer));

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("main", _hoisted_1, [
    _createElementVNode("section", _hoisted_2, [
      _cache[6] || (_cache[6] = _createElementVNode("div", null, [
        _createElementVNode("p", { class: "eyebrow" }, "MediaGovernor 5.0.0"),
        _createElementVNode("h1", null, "检查现在，找到真实问题"),
        _createElementVNode("p", { class: "lead" }, "逐作品比较原文件、当前硬链接和 MoviePilot 应有结果。已经完成的结果会立即保存，关掉页面也不会中断。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        (running.value)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "secondary",
              onClick: cancel
            }, "停止后续检查"))
          : _createCommentVNode("", true),
        _createElementVNode("button", {
          class: "primary",
          disabled: busy.value || running.value,
          onClick: _cache[0] || (_cache[0] = $event => (start('incremental')))
        }, "检查现在", 8, _hoisted_4),
        _createElementVNode("details", _hoisted_5, [
          _cache[4] || (_cache[4] = _createElementVNode("summary", null, "高级操作", -1)),
          _createElementVNode("button", {
            class: "secondary",
            disabled: busy.value || running.value,
            onClick: _cache[1] || (_cache[1] = $event => (start('full')))
          }, "重建全部基线", 8, _hoisted_6),
          _cache[5] || (_cache[5] = _createElementVNode("p", null, "只在首次使用、目录配置改变或诊断时运行。", -1))
        ])
      ])
    ]),
    _createElementVNode("section", _hoisted_7, [
      _createElementVNode("div", _hoisted_8, [
        _createElementVNode("div", null, [
          _createElementVNode("b", null, _toDisplayString(running.value ? '正在后台检查' : job.value.status === 'completed' ? '检查完成' : job.value.status === 'failed' ? '检查失败' : '等待检查'), 1),
          _createElementVNode("span", null, _toDisplayString(job.value.current), 1)
        ]),
        _createElementVNode("strong", null, _toDisplayString(job.value.done || 0) + "/" + _toDisplayString(job.value.total || 0), 1)
      ]),
      (running.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_9, [
            _createElementVNode("i", {
              style: _normalizeStyle({ width: `${progress.value}%` })
            }, null, 4)
          ]))
        : _createCommentVNode("", true),
      (job.value.error)
        ? (_openBlock(), _createElementBlock("p", _hoisted_10, _toDisplayString(job.value.error), 1))
        : _createCommentVNode("", true),
      (message.value)
        ? (_openBlock(), _createElementBlock("p", _hoisted_11, _toDisplayString(message.value), 1))
        : _createCommentVNode("", true)
    ]),
    _createElementVNode("section", _hoisted_12, [
      _createElementVNode("article", null, [
        _createElementVNode("strong", null, _toDisplayString(snapshot.value.problems.length), 1),
        _cache[7] || (_cache[7] = _createElementVNode("span", null, "已经证明的问题", -1))
      ]),
      _createElementVNode("article", null, [
        _createElementVNode("strong", null, _toDisplayString(snapshot.value.confirmations.length), 1),
        _cache[8] || (_cache[8] = _createElementVNode("span", null, "需要你确认", -1))
      ]),
      _createElementVNode("article", null, [
        _createElementVNode("strong", null, _toDisplayString(snapshot.value.errors.length), 1),
        _cache[9] || (_cache[9] = _createElementVNode("span", null, "本轮没读完", -1))
      ]),
      _createElementVNode("article", null, [
        _createElementVNode("strong", null, _toDisplayString(snapshot.value.status.objects || 0), 1),
        _cache[10] || (_cache[10] = _createElementVNode("span", null, "当前作品", -1))
      ])
    ]),
    _createElementVNode("section", _hoisted_13, [
      _createElementVNode("header", null, [
        _cache[11] || (_cache[11] = _createElementVNode("div", null, [
          _createElementVNode("p", { class: "eyebrow" }, "发现的问题"),
          _createElementVNode("h2", null, "整理失败和假成功")
        ], -1)),
        _createElementVNode("span", null, _toDisplayString(snapshot.value.problems.length) + " 项", 1)
      ]),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(snapshot.value.problems, (item) => {
        return (_openBlock(), _createElementBlock("button", {
          key: item.id,
          class: "result-row",
          onClick: $event => (openItem(item))
        }, [
          _createElementVNode("span", null, [
            _createElementVNode("b", null, _toDisplayString(item.title), 1),
            _createElementVNode("small", null, _toDisplayString(item.reason), 1)
          ]),
          _cache[12] || (_cache[12] = _createElementVNode("i", null, "查看证据与修复 →", -1))
        ], 8, _hoisted_14))
      }), 128)),
      (!snapshot.value.problems.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_15, _toDisplayString(running.value ? '已完成的作品还没有形成问题。' : hasResults.value ? '当前没有已经证明的问题。' : '点击“检查现在”开始。'), 1))
        : _createCommentVNode("", true)
    ]),
    _createElementVNode("section", _hoisted_16, [
      _createElementVNode("header", null, [
        _cache[13] || (_cache[13] = _createElementVNode("div", null, [
          _createElementVNode("p", { class: "eyebrow" }, "需要你确认"),
          _createElementVNode("h2", null, "身份歧义或手工改动")
        ], -1)),
        _createElementVNode("span", null, _toDisplayString(snapshot.value.confirmations.length) + " 项", 1)
      ]),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(snapshot.value.confirmations, (item) => {
        return (_openBlock(), _createElementBlock("button", {
          key: item.id,
          class: "result-row",
          onClick: $event => (openItem(item))
        }, [
          _createElementVNode("span", null, [
            _createElementVNode("b", null, _toDisplayString(item.title), 1),
            _createElementVNode("small", null, _toDisplayString(item.reason), 1)
          ]),
          _cache[14] || (_cache[14] = _createElementVNode("i", null, "选择正确答案 →", -1))
        ], 8, _hoisted_17))
      }), 128)),
      (!snapshot.value.confirmations.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_18, "没有等待你决定的项目。"))
        : _createCommentVNode("", true)
    ]),
    _createElementVNode("section", _hoisted_19, [
      _createElementVNode("header", null, [
        _cache[15] || (_cache[15] = _createElementVNode("div", null, [
          _createElementVNode("p", { class: "eyebrow" }, "本轮没读完"),
          _createElementVNode("h2", null, "明确的读取或预览错误")
        ], -1)),
        _createElementVNode("span", null, _toDisplayString(snapshot.value.errors.length) + " 项", 1)
      ]),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(snapshot.value.errors, (item) => {
        return (_openBlock(), _createElementBlock("button", {
          key: item.id,
          class: "result-row",
          onClick: $event => (openItem(item))
        }, [
          _createElementVNode("span", null, [
            _createElementVNode("b", null, _toDisplayString(item.title), 1),
            _createElementVNode("small", null, _toDisplayString(item.reason), 1)
          ]),
          _cache[16] || (_cache[16] = _createElementVNode("i", null, "查看失败阶段 →", -1))
        ], 8, _hoisted_20))
      }), 128)),
      (!snapshot.value.errors.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_21, "没有读取错误。"))
        : _createCommentVNode("", true)
    ]),
    (selected.value)
      ? (_openBlock(), _createElementBlock("div", {
          key: 0,
          class: "backdrop",
          onClick: _withModifiers(closeDetail, ["self"])
        }, [
          _createElementVNode("section", {
            class: "modal",
            role: "dialog",
            "aria-modal": "true",
            "aria-label": selected.value.title
          }, [
            _createElementVNode("button", {
              class: "close",
              "aria-label": "关闭",
              onClick: closeDetail
            }, "×"),
            _cache[25] || (_cache[25] = _createElementVNode("p", { class: "eyebrow" }, "作品证据", -1)),
            _createElementVNode("h2", null, _toDisplayString(selected.value.title), 1),
            _createElementVNode("p", _hoisted_23, _toDisplayString(selected.value.finding?.reason), 1),
            _createElementVNode("div", _hoisted_24, [
              _createElementVNode("div", null, [
                _cache[17] || (_cache[17] = _createElementVNode("span", null, "文件读取", -1)),
                _createElementVNode("b", null, _toDisplayString(selected.value.source?.object?.complete ? '完整' : '未完整'), 1)
              ]),
              _createElementVNode("div", null, [
                _cache[18] || (_cache[18] = _createElementVNode("span", null, "作品身份", -1)),
                _createElementVNode("b", null, _toDisplayString(selected.value.identity_state === 'confirmed' ? '已确认' : '等待确认'), 1)
              ]),
              _createElementVNode("div", null, [
                _cache[19] || (_cache[19] = _createElementVNode("span", null, "确认依据", -1)),
                _createElementVNode("b", null, _toDisplayString(selected.value.provenance || '暂无'), 1)
              ])
            ]),
            (selected.value.identity_state !== 'confirmed')
              ? (_openBlock(), _createElementBlock("section", _hoisted_25, [
                  _cache[20] || (_cache[20] = _createElementVNode("h3", null, "请选择正确作品", -1)),
                  (!selected.value.candidates.length)
                    ? (_openBlock(), _createElementBlock("p", _hoisted_26, "MoviePilot 和智能助手都没有给出可用候选。本项会保留，不会被算成正常。"))
                    : _createCommentVNode("", true),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selected.value.candidates, (candidate) => {
                    return (_openBlock(), _createElementBlock("button", {
                      key: candidateKey(candidate),
                      class: "candidate",
                      disabled: busy.value,
                      onClick: $event => (confirmIdentity(candidate))
                    }, [
                      _createElementVNode("b", null, _toDisplayString(candidate.title || candidate.original_title || '未命名候选'), 1),
                      _createElementVNode("span", null, _toDisplayString(candidate.year || '年份未知') + " · " + _toDisplayString(candidate.media_type) + " · " + _toDisplayString(candidate.media_source) + "/" + _toDisplayString(candidate.media_id), 1)
                    ], 8, _hoisted_27))
                  }), 128))
                ]))
              : (_openBlock(), _createElementBlock("section", _hoisted_28, [
                  _createElementVNode("h3", null, _toDisplayString(selected.value.identity.title || selected.value.identity.original_title), 1),
                  _createElementVNode("p", null, _toDisplayString(selected.value.identity.year || '年份未知') + " · " + _toDisplayString(selected.value.identity.media_type) + " · " + _toDisplayString(selected.value.identity.media_source) + "/" + _toDisplayString(selected.value.identity.media_id), 1),
                  _createElementVNode("button", {
                    class: "primary",
                    disabled: busy.value,
                    onClick: previewRepair
                  }, "重新读取并生成修复预览", 8, _hoisted_29)
                ])),
            (repairPlan.value)
              ? (_openBlock(), _createElementBlock("section", _hoisted_30, [
                  _cache[22] || (_cache[22] = _createElementVNode("h3", null, "整理前后对比", -1)),
                  _cache[23] || (_cache[23] = _createElementVNode("div", { class: "compare-head" }, [
                    _createElementVNode("b", null, "原文件"),
                    _createElementVNode("b", null, "当前硬链接"),
                    _createElementVNode("b", null, "修复后")
                  ], -1)),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(repairPlan.value.entries, (row, index) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: index,
                      class: "compare-row"
                    }, [
                      _createElementVNode("span", null, _toDisplayString(row.source?.path), 1),
                      _createElementVNode("span", null, _toDisplayString(row.current || '没有建立'), 1),
                      _createElementVNode("span", null, _toDisplayString(row.expected), 1)
                    ]))
                  }), 128)),
                  _cache[24] || (_cache[24] = _createElementVNode("p", { class: "warning" }, "只会清理这里列出的旧硬链接，再由 MoviePilot 官方整理链重建；不会删除原始下载。", -1)),
                  (!confirmingRepair.value)
                    ? (_openBlock(), _createElementBlock("button", {
                        key: 0,
                        class: "danger",
                        onClick: _cache[2] || (_cache[2] = $event => (confirmingRepair.value = true))
                      }, "继续到最终确认"))
                    : (_openBlock(), _createElementBlock("div", _hoisted_31, [
                        _cache[21] || (_cache[21] = _createElementVNode("b", null, "确认执行这一个作品？", -1)),
                        _createElementVNode("button", {
                          class: "secondary",
                          onClick: _cache[3] || (_cache[3] = $event => (confirmingRepair.value = false))
                        }, "返回"),
                        _createElementVNode("button", {
                          class: "danger",
                          disabled: busy.value,
                          onClick: executeRepair
                        }, "确认修复", 8, _hoisted_32)
                      ]))
                ]))
              : _createCommentVNode("", true)
          ], 8, _hoisted_22)
        ]))
      : _createCommentVNode("", true)
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-5078908d"]]);

export { AppPage as default };
