import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "course-config__section" };
const _hoisted_2 = { class: "d-flex align-center mb-2" };
const _hoisted_3 = { class: "course-config__section" };
const _hoisted_4 = { class: "d-flex align-center mb-2" };
const _hoisted_5 = { class: "course-config__actions" };

const {ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const localConfig = ref({});
const saving = ref(false);
const validationMessage = ref('');

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function textValue(value) {
  return String(value ?? '').trim()
}

function nextArchiveKey(index) {
  return 'archive_' + Date.now() + '_' + (index + 1)
}

function normalizeDownloads(config) {
  const values = Array.isArray(config.download_directories)
    ? config.download_directories
    : (textValue(config.incoming) ? [{ name: '下载目录', path: config.incoming }] : []);
  return values
    .filter(item => typeof item === 'string' || (item && typeof item === 'object'))
    .map((item, index) => {
      const value = typeof item === 'string' ? { path: item } : item;
      return {
        name: textValue(value.name || value.label) || '下载目录 ' + (index + 1),
        path: textValue(value.path),
      }
    })
}

function normalizeArchives(config) {
  let values = config.archive_directories;
  if (!Array.isArray(values)) {
    const hasLegacy = ['tv_output', 'movie_output', 'children_output', 'output']
      .some(key => Object.prototype.hasOwnProperty.call(config, key));
    values = hasLegacy
      ? [
          { key: 'tv', name: '电视剧', path: config.tv_output, media_type: 'tv' },
          { key: 'movie', name: '电影', path: config.movie_output, media_type: 'movie' },
          {
            key: 'children',
            name: '儿童课程',
            path: config.children_output ?? config.output,
            media_type: 'tv',
            category: '儿童',
          },
        ]
      : [];
  }
  return values
    .filter(item => typeof item === 'string' || (item && typeof item === 'object'))
    .map((item, index) => {
      const value = typeof item === 'string' ? { path: item } : item;
      const key = textValue(value.key || value.id) || nextArchiveKey(index);
      return {
        id: textValue(value.id) || key,
        key,
        name: textValue(value.name || value.label) || '归档目录 ' + (index + 1),
        path: textValue(value.path),
        media_type: textValue(value.media_type),
        category: textValue(value.category || value.media_category),
      }
    })
}

function normalizeInitialConfig(value) {
  const config = clone(value);
  const rawAutoOrganize = Object.prototype.hasOwnProperty.call(config, 'auto_organize')
    ? config.auto_organize
    : String(config.naming_mode || '').trim().toLowerCase() === 'apply';
  const autoOrganize = typeof rawAutoOrganize === 'string'
    ? ['1', 'true', 'yes', 'on'].includes(rawAutoOrganize.trim().toLowerCase())
    : Boolean(rawAutoOrganize);
  return {
    ...config,
    download_directories: normalizeDownloads(config),
    archive_directories: normalizeArchives(config),
    auto_organize: autoOrganize,
  }
}

function addDownloadDirectory() {
  const items = localConfig.value.download_directories;
  items.push({ name: '下载目录 ' + (items.length + 1), path: '' });
}

function removeDownloadDirectory(index) {
  localConfig.value.download_directories.splice(index, 1);
}

function addArchiveDirectory() {
  const items = localConfig.value.archive_directories;
  const index = items.length;
  const key = nextArchiveKey(index);
  items.push({
    id: key,
    key,
    name: '归档目录 ' + (index + 1),
    path: '',
    media_type: '',
    category: '',
  });
}

function removeArchiveDirectory(index) {
  localConfig.value.archive_directories.splice(index, 1);
}

function validateDirectories() {
  const downloads = localConfig.value.download_directories;
  const archives = localConfig.value.archive_directories;
  if (!downloads.length || !archives.length) {
    return '请至少添加一个下载目录和一个归档目录。'
  }
  if (downloads.some(item => !textValue(item.name) || !textValue(item.path))) {
    return '请完整填写每个下载目录的名称和路径。'
  }
  const keys = new Set();
  for (const item of archives) {
    const key = textValue(item.key || item.id).toLowerCase();
    if (!key || !textValue(item.name) || !textValue(item.path)) {
      return '请完整填写每个归档目录的标识、名称和路径。'
    }
    if (keys.has(key)) return '归档目录标识不能重复。'
    keys.add(key);
  }
  return ''
}

function saveConfig() {
  if (saving.value) return
  validationMessage.value = validateDirectories();
  if (validationMessage.value) return
  saving.value = true;
  try {
    emit('save', clone(localConfig.value));
  } finally {
    saving.value = false;
  }
}

watch(
  () => props.initialConfig,
  value => {
    localConfig.value = normalizeInitialConfig(value);
  },
  { immediate: true, deep: true },
);

return (_ctx, _cache) => {
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VForm = _resolveComponent("VForm");

  return (_openBlock(), _createBlock(_component_VForm, {
    class: "course-config",
    "aria-label": "课程整理目录设置",
    onSubmit: _withModifiers(saveConfig, ["prevent"])
  }, {
    default: _withCtx(() => [
      _createVNode(_component_VToolbar, {
        density: "comfortable",
        color: "transparent",
        class: "course-config__toolbar"
      }, {
        default: _withCtx(() => [
          _cache[3] || (_cache[3] = _createElementVNode("div", { class: "text-h6" }, "课程整理目录", -1)),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            icon: "mdi-close",
            variant: "text",
            "aria-label": "关闭设置",
            onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VDivider),
      _createVNode(_component_VAlert, {
        type: "info",
        variant: "tonal",
        class: "ma-3",
        role: "note"
      }, {
        default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
          _createTextVNode(" 插件独立维护下载目录和归档目录，不读取 MoviePilot 的目录设置。可配置多个下载目录和多个归档目录；共享配置时，请由接收者填写自己设备上的绝对路径。 ", -1)
        ]))]),
        _: 1
      }),
      _createElementVNode("section", _hoisted_1, [
        _createElementVNode("div", _hoisted_2, [
          _cache[6] || (_cache[6] = _createElementVNode("div", { class: "text-subtitle-1" }, "下载目录", -1)),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            size: "small",
            variant: "tonal",
            "prepend-icon": "mdi-plus",
            onClick: addDownloadDirectory
          }, {
            default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
              _createTextVNode(" 添加下载目录 ", -1)
            ]))]),
            _: 1
          })
        ]),
        (!localConfig.value.download_directories.length)
          ? (_openBlock(), _createBlock(_component_VAlert, {
              key: 0,
              type: "warning",
              variant: "tonal",
              density: "compact",
              class: "mb-3"
            }, {
              default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                _createTextVNode(" 至少需要一个下载目录。 ", -1)
              ]))]),
              _: 1
            }))
          : _createCommentVNode("", true),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(localConfig.value.download_directories, (directory, index) => {
          return (_openBlock(), _createElementBlock("div", {
            key: directory.name + '-' + index,
            class: "course-config__directory-row"
          }, [
            _createVNode(_component_VTextField, {
              modelValue: directory.name,
              "onUpdate:modelValue": $event => ((directory.name) = $event),
              label: "名称",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VTextField, {
              modelValue: directory.path,
              "onUpdate:modelValue": $event => ((directory.path) = $event),
              label: "路径",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VBtn, {
              icon: "mdi-delete-outline",
              variant: "text",
              color: "error",
              "aria-label": '删除下载目录 ' + (index + 1),
              onClick: $event => (removeDownloadDirectory(index))
            }, null, 8, ["aria-label", "onClick"])
          ]))
        }), 128))
      ]),
      _createElementVNode("section", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _cache[9] || (_cache[9] = _createElementVNode("div", { class: "text-subtitle-1" }, "归档目录", -1)),
          _createVNode(_component_VSpacer),
          _createVNode(_component_VBtn, {
            size: "small",
            variant: "tonal",
            "prepend-icon": "mdi-plus",
            onClick: addArchiveDirectory
          }, {
            default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
              _createTextVNode(" 添加归档目录 ", -1)
            ]))]),
            _: 1
          })
        ]),
        (!localConfig.value.archive_directories.length)
          ? (_openBlock(), _createBlock(_component_VAlert, {
              key: 0,
              type: "warning",
              variant: "tonal",
              density: "compact",
              class: "mb-3"
            }, {
              default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                _createTextVNode(" 至少需要一个归档目录。 ", -1)
              ]))]),
              _: 1
            }))
          : _createCommentVNode("", true),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(localConfig.value.archive_directories, (directory, index) => {
          return (_openBlock(), _createElementBlock("div", {
            key: directory.id || directory.key || index,
            class: "course-config__archive-row"
          }, [
            _createVNode(_component_VTextField, {
              modelValue: directory.key,
              "onUpdate:modelValue": $event => ((directory.key) = $event),
              label: "标识",
              hint: "供人工确认选择，不能重复。",
              "persistent-hint": "",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VTextField, {
              modelValue: directory.name,
              "onUpdate:modelValue": $event => ((directory.name) = $event),
              label: "名称",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VTextField, {
              modelValue: directory.path,
              "onUpdate:modelValue": $event => ((directory.path) = $event),
              label: "路径",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VTextField, {
              modelValue: directory.media_type,
              "onUpdate:modelValue": $event => ((directory.media_type) = $event),
              label: "媒体类型（可选）",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VTextField, {
              modelValue: directory.category,
              "onUpdate:modelValue": $event => ((directory.category) = $event),
              label: "分类（可选）",
              density: "comfortable"
            }, null, 8, ["modelValue", "onUpdate:modelValue"]),
            _createVNode(_component_VBtn, {
              icon: "mdi-delete-outline",
              variant: "text",
              color: "error",
              "aria-label": '删除归档目录 ' + (index + 1),
              onClick: $event => (removeArchiveDirectory(index))
            }, null, 8, ["aria-label", "onClick"])
          ]))
        }), 128)),
        _createVNode(_component_VAlert, {
          type: "info",
          variant: "tonal",
          density: "compact"
        }, {
          default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
            _createTextVNode(" 自动识别仍使用现有 tv、movie、children 内置类型映射；其他归档目录可在人工确认时选择。 ", -1)
          ]))]),
          _: 1
        })
      ]),
      _createVNode(_component_VSwitch, {
        modelValue: localConfig.value.auto_organize,
        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((localConfig.value.auto_organize) = $event)),
        class: "mx-4 mb-2",
        label: "自动整理符合条件的项目",
        hint: "未完整配置目录或下载目录不可读取时，插件只保留安全预览。",
        "persistent-hint": "",
        color: "primary"
      }, null, 8, ["modelValue"]),
      (validationMessage.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: "error",
            variant: "tonal",
            density: "compact",
            class: "mx-3 mb-3"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(validationMessage.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      _createElementVNode("div", _hoisted_5, [
        _createVNode(_component_VBtn, {
          variant: "text",
          "min-width": "88",
          onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
            _createTextVNode("取消", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_VBtn, {
          color: "primary",
          "min-width": "108",
          loading: saving.value,
          onClick: saveConfig
        }, {
          default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
            _createTextVNode("保存", -1)
          ]))]),
          _: 1
        }, 8, ["loading"])
      ])
    ]),
    _: 1
  }))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-660c0047"]]);

export { Config as default };
