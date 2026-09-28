import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,vModelText:_vModelText,withDirectives:_withDirectives,createTextVNode:_createTextVNode,toDisplayString:_toDisplayString,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "config-page" };
const _hoisted_2 = {
  key: 0,
  class: "notice"
};
const _hoisted_3 = {
  key: 1,
  class: "form-grid"
};
const _hoisted_4 = { class: "wide" };
const _hoisted_5 = { class: "wide" };
const _hoisted_6 = {
  key: 2,
  class: "error"
};
const _hoisted_7 = {
  key: 3,
  class: "success"
};
const _hoisted_8 = {
  key: 4,
  class: "probe"
};
const _hoisted_9 = { key: 0 };
const _hoisted_10 = ["disabled"];

const {computed,onMounted,reactive,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
},
  setup(__props) {

const props = __props;

const form = reactive({
  version: 1,
  ssh_host: '',
  qb_url: '',
  jellyfin_db: '',
  moviepilot_db: '',
  qb_backup: '',
  execution_backup: '',
  allowed_roots_text: '',
  quarantine_roots_text: '',
});
const loading = ref(true);
const saving = ref(false);
const error = ref('');
const message = ref('');
const probe = ref(null);

const pluginBase = computed(() => `plugin/${props.pluginId || 'StorageCleanup'}`);

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data')) {
    return response.data
  }
  return response
}

function applyConfig(config) {
  Object.assign(form, {
    ...config,
    allowed_roots_text: (config.allowed_roots || []).join('\n'),
    quarantine_roots_text: Object.entries(config.quarantine_roots || {})
      .map(([volume, target]) => `${volume}=${target}`)
      .join('\n'),
  });
}

function parseLines(value) {
  return String(value || '')
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean)
}

function buildConfig() {
  const quarantine_roots = {};
  for (const line of parseLines(form.quarantine_roots_text)) {
    const separator = line.indexOf('=');
    if (separator <= 0 || separator === line.length - 1) {
      throw new Error('隔离目录格式应为：卷根目录=隔离目录。')
    }
    quarantine_roots[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
  }
  return {
    version: 1,
    ssh_host: form.ssh_host,
    qb_url: form.qb_url,
    jellyfin_db: form.jellyfin_db,
    moviepilot_db: form.moviepilot_db,
    qb_backup: form.qb_backup,
    execution_backup: form.execution_backup,
    allowed_roots: parseLines(form.allowed_roots_text),
    quarantine_roots,
  }
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    if (!props.api.get) throw new Error('MoviePilot 没有提供插件 API。')
    const payload = unwrap(await props.api.get(`${pluginBase.value}/config`));
    if (!payload?.ok || !payload.config) throw new Error(payload?.error?.message || '无法读取清理台配置。')
    applyConfig(payload.config);
    probe.value = payload.probe || null;
  } catch (err) {
    error.value = err?.message || '无法读取清理台配置。';
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = '';
  message.value = '';
  try {
    const config = buildConfig();
    const payload = unwrap(await props.api.post(`${pluginBase.value}/config`, { config }));
    if (!payload?.ok || !payload.config) throw new Error(payload?.error?.message || '配置保存失败。')
    applyConfig(payload.config);
    probe.value = payload.probe || null;
    message.value = probe.value?.ok
      ? '配置已保存，路径探测通过；请刷新资源清单。'
      : '配置已保存，但仍有路径未就绪；清理操作保持锁定。';
  } catch (err) {
    const payload = err?.response?.data || err?.data;
    probe.value = payload?.probe || probe.value;
    error.value = err?.message || payload?.error?.message || '配置保存失败。';
  } finally {
    saving.value = false;
  }
}

onMounted(load);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _cache[16] || (_cache[16] = _createElementVNode("header", null, [
      _createElementVNode("h2", null, "存储清理设置"),
      _createElementVNode("p", null, "这里只保存 NAS 拓扑和路径，不会写入 Cookie、passkey 或控制令牌。保存后先做只读探测，未通过探测时清理操作保持锁定。")
    ], -1)),
    (loading.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_2, "正在读取配置…"))
      : (_openBlock(), _createElementBlock("div", _hoisted_3, [
          _createElementVNode("label", null, [
            _cache[8] || (_cache[8] = _createTextVNode("SSH 目标", -1)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((form.ssh_host) = $event)),
              autocomplete: "off"
            }, null, 512), [
              [_vModelText, form.ssh_host]
            ])
          ]),
          _createElementVNode("label", null, [
            _cache[9] || (_cache[9] = _createTextVNode("qBittorrent 地址", -1)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((form.qb_url) = $event)),
              autocomplete: "off"
            }, null, 512), [
              [_vModelText, form.qb_url]
            ])
          ]),
          _createElementVNode("label", null, [
            _cache[10] || (_cache[10] = _createTextVNode("Jellyfin 数据库", -1)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.jellyfin_db) = $event)),
              autocomplete: "off"
            }, null, 512), [
              [_vModelText, form.jellyfin_db]
            ])
          ]),
          _createElementVNode("label", null, [
            _cache[11] || (_cache[11] = _createTextVNode("MoviePilot 数据库", -1)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.moviepilot_db) = $event)),
              autocomplete: "off"
            }, null, 512), [
              [_vModelText, form.moviepilot_db]
            ])
          ]),
          _createElementVNode("label", null, [
            _cache[12] || (_cache[12] = _createTextVNode("qB 种子备份目录", -1)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((form.qb_backup) = $event)),
              autocomplete: "off"
            }, null, 512), [
              [_vModelText, form.qb_backup]
            ])
          ]),
          _createElementVNode("label", null, [
            _cache[13] || (_cache[13] = _createTextVNode("清理事务备份目录", -1)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.execution_backup) = $event)),
              autocomplete: "off"
            }, null, 512), [
              [_vModelText, form.execution_backup]
            ])
          ]),
          _createElementVNode("label", _hoisted_4, [
            _cache[14] || (_cache[14] = _createTextVNode("允许扫描/清理的根目录（每行一个）", -1)),
            _withDirectives(_createElementVNode("textarea", {
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.allowed_roots_text) = $event)),
              rows: "6"
            }, null, 512), [
              [_vModelText, form.allowed_roots_text]
            ])
          ]),
          _createElementVNode("label", _hoisted_5, [
            _cache[15] || (_cache[15] = _createTextVNode("隔离目录映射（每行：卷根目录=隔离目录）", -1)),
            _withDirectives(_createElementVNode("textarea", {
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.quarantine_roots_text) = $event)),
              rows: "4"
            }, null, 512), [
              [_vModelText, form.quarantine_roots_text]
            ])
          ])
        ])),
    (error.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_6, _toDisplayString(error.value), 1))
      : _createCommentVNode("", true),
    (message.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_7, _toDisplayString(message.value), 1))
      : _createCommentVNode("", true),
    (probe.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_8, [
          _createElementVNode("strong", null, _toDisplayString(probe.value.ok ? '只读探测通过' : '只读探测未通过'), 1),
          (probe.value.missing?.length)
            ? (_openBlock(), _createElementBlock("span", _hoisted_9, "未找到：" + _toDisplayString(probe.value.missing.join('、')), 1))
            : _createCommentVNode("", true),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(probe.value.problems || [], (item) => {
            return (_openBlock(), _createElementBlock("span", { key: item }, _toDisplayString(item), 1))
          }), 128))
        ]))
      : _createCommentVNode("", true),
    _createElementVNode("button", {
      class: "save",
      disabled: loading.value || saving.value,
      onClick: save
    }, _toDisplayString(saving.value ? '保存中…' : '保存并探测'), 9, _hoisted_10)
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-54d4575f"]]);

export { Config as default };
