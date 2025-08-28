import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { V as VAceEditor } from './theme-monokai-Bn79mBHh.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,mergeProps:_mergeProps,withModifiers:_withModifiers,createElementVNode:_createElementVNode,unref:_unref,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "d-flex align-center" };
const _hoisted_3 = { class: "font-weight-medium" };
const _hoisted_4 = { class: "text-body-2" };

const {ref,reactive,onMounted,computed} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
  api: {
    type: Object,
    default: () => {
    },
  },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const activeTab = ref("subscription");
const editorOptions = {
  enableBasicAutocompletion: true,
  enableSnippets: true,
  enableLiveAutocompletion: true,
  showLineNumbers: true,
  tabSize: 2
};
const configPlaceholder = ref(
    `profile:
  store-selected: true
mode: rule
log-level: silent`
);
// Props
const props = __props;

// 状态变量
const clashTemplateDialog = ref(false);
const clashTemplateType = ref('YAML');
const clashTemplateContent = ref('');
const form = ref(null);
const isFormValid = ref(true);
const error = ref(null);
const saving = ref(false);
const testing = ref(false);
const showClashSecret = ref(false);
const dashboardComponents = ['Clash Info', 'Traffic Stats'];

// Test result state
const testResult = reactive({
  show: false,
  success: false,
  title: '',
  message: ''
});


// 默认配置
const defaultConfig = {
  enabled: false,
  sub_links: [],
  filter_keywords: ["公益性", "高延迟", "域名", "官网", "重启", "过期时间", "系统代理"],
  clash_dashboard_url: '',
  clash_dashboard_secret: '',
  movie_pilot_url: '',
  cron_string: '0 */6 * * *',
  timeout: 10,
  retry_times: 3,
  proxy: false,
  notify: false,
  auto_update_subscriptions: true,
  ruleset_prefix: '📂<=',
  acl4ssr_prefix: '🗂️=>',
  group_by_region: false,
  group_by_country: false,
  refresh_delay: 5,
  discard_rules: false,
  discard_proxy_groups: false,
  enable_acl4ssr: false,
  dashboard_components: [],
  clash_template: '',
  hint_geo_dat: false,
  best_cf_ip: []
};

// 响应式配置对象
const config = reactive({...defaultConfig});

// 自定义事件
const emit = __emit;

// 初始化
onMounted(() => {
  if (props.initialConfig) {
    Object.keys(props.initialConfig).forEach(key => {
      if (key in config) {
        config[key] = props.initialConfig[key];
      }
    });
  }
});

// 验证函数
const isValidUrl = (urlString) => {
  if (!urlString) return false;
  try {
    const url = new URL(urlString);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch (e) {
    return false;
  }
};

function validateSubLinks(links) {
  for (const link of links) {
    if (!isValidUrl(link)) {
      return `无效的订阅链接: ${link}`
    }
  }
  return true
}

function isValidIP(ip) {
  // IPv4 正则：四段数字（0–255），用点隔开
  const ipv4Regex = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;

  // IPv6 正则：八组 1–4 位 16 进制数，用冒号隔开，支持简写 ::（不严格支持所有极端情况，但能覆盖大多数合法 IPv6）
  const ipv6Regex = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(([0-9a-fA-F]{1,4}:){1,7}|:):([0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4})$/;

  return ipv4Regex.test(ip) || ipv6Regex.test(ip);
}

function validateIPs(ips) {
  for (const ip of ips) {
    if (!isValidIP(ip)) {
      return `无效的 IP 地址: ${ip}`
    }
  }
  return true
}

// 测试连接
async function testConnection() {
  testing.value = true;
  error.value = null;
  testResult.show = false;

  try {
    // 验证必需的参数
    if (!config.clash_dashboard_url) {
      throw new Error('请先配置 Clash 面板 URL')
    }
    if (!config.clash_dashboard_secret) {
      throw new Error('请先配置 Clash 面板密钥')
    }
    if (!config.sub_links || config.sub_links.length === 0) {
      throw new Error('请先配置至少一个订阅链接')
    }
    if (!config.movie_pilot_url || config.movie_pilot_url.length === 0) {
      throw new Error('请先MoviePilot链接')
    }
    // 准备API请求参数
    const testParams = {
      clash_dashboard_url: config.clash_dashboard_url,
      clash_dashboard_secret: config.clash_dashboard_secret,
      sub_links: config.sub_links // 使用第一个订阅链接进行测试
    };

    // 调用API进行连接测试
    const result = await props.api.post('/plugin/ClashRuleProvider/connectivity', testParams);

    // 根据返回结果显示相应消息
    if (result.success) {
      testResult.success = true;
      testResult.title = '连接测试成功！';
      testResult.message = 'Clash面板和订阅链接连接正常，配置验证通过';
      testResult.show = true;

      // Auto hide after 5 seconds
      setTimeout(() => {
        testResult.show = false;
      }, 5000);
    } else {
      throw new Error(result.message || '连接测试失败，请检查配置')
    }

  } catch (err) {
    console.error('连接测试失败:', err);
    testResult.success = false;
    testResult.title = '连接测试失败';
    testResult.message = err.message;
    testResult.show = true;
  } finally {
    testing.value = false;
  }
}

// 保存配置
async function saveConfig() {
  if (!isFormValid.value) {
    error.value = '请修正表单中的错误';
    return
  }

  saving.value = true;
  error.value = null;

  try {
    await new Promise(resolve => setTimeout(resolve, 1000));
    emit('save', {...config});
  } catch (err) {
    console.error('保存配置失败:', err);
    error.value = err.message || '保存配置失败';
  } finally {
    saving.value = false;
  }
}

function extractDomain(url) {
  try {
    const domain = new URL(url).hostname;
    return domain.startsWith('www.') ? domain.substring(4) : domain
  } catch {
    return url // 如果解析失败，返回原始URL
  }
}

function openClashTemplateDialog() {
  clashTemplateContent.value = config.clash_template;
  clashTemplateDialog.value = true;
}

function saveClashTemplate() {
  config.clash_template = clashTemplateContent.value;
  clashTemplateDialog.value = false;
}

// 重置表单
function resetForm() {
  Object.keys(defaultConfig).forEach(key => {
    config[key] = defaultConfig[key];
  });

  if (form.value) {
    form.value.resetValidation();
  }
}

// 关闭组件
function notifyClose() {
  emit('close');
}

// 通知主应用切换到Page页面
function notifySwitch() {
  emit('switch');
}

return (_ctx, _cache) => {
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_tab = _resolveComponent("v-tab");
  const _component_v_tabs = _resolveComponent("v-tabs");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_combobox = _resolveComponent("v-combobox");
  const _component_v_window_item = _resolveComponent("v-window-item");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_cron_field = _resolveComponent("v-cron-field");
  const _component_v_window = _resolveComponent("v-window");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_form = _resolveComponent("v-form");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (_openBlock(), _createElementBlock(_Fragment, null, [
    _createElementVNode("div", _hoisted_1, [
      _createVNode(_component_v_card, null, {
        default: _withCtx(() => [
          _createVNode(_component_v_card_item, null, {
            append: _withCtx(() => [
              _createVNode(_component_v_btn, {
                icon: "",
                color: "primary",
                variant: "text",
                onClick: notifyClose
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, { left: "" }, {
                    default: _withCtx(() => _cache[33] || (_cache[33] = [
                      _createTextVNode("mdi-close")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            default: _withCtx(() => [
              _createVNode(_component_v_card_title, null, {
                default: _withCtx(() => _cache[32] || (_cache[32] = [
                  _createTextVNode("Clash Rule Provider 插件配置")
                ])),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_v_card_text, { class: "overflow-y-auto" }, {
            default: _withCtx(() => [
              (error.value)
                ? (_openBlock(), _createBlock(_component_v_alert, {
                    key: 0,
                    type: "error",
                    class: "mb-4"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(error.value), 1)
                    ]),
                    _: 1
                  }))
                : _createCommentVNode("", true),
              _createVNode(_component_v_form, {
                ref_key: "form",
                ref: form,
                modelValue: isFormValid.value,
                "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((isFormValid).value = $event)),
                onSubmit: _withModifiers(saveConfig, ["prevent"])
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_row, null, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_col, {
                        cols: "12",
                        md: "3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_switch, {
                            modelValue: config.enabled,
                            "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
                            label: "启用插件",
                            color: "primary",
                            inset: "",
                            density: "compact",
                            hint: "启用插件"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_col, {
                        cols: "12",
                        md: "3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_switch, {
                            modelValue: config.proxy,
                            "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.proxy) = $event)),
                            label: "启用代理",
                            color: "primary",
                            inset: "",
                            density: "compact",
                            hint: "是否使用系统代理进行网络请求"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_col, {
                        cols: "12",
                        md: "3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_switch, {
                            modelValue: config.notify,
                            "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.notify) = $event)),
                            label: "启用通知",
                            color: "primary",
                            inset: "",
                            density: "compact",
                            hint: "执行完成后发送通知消息"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_col, {
                        cols: "12",
                        md: "3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_switch, {
                            modelValue: config.auto_update_subscriptions,
                            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.auto_update_subscriptions) = $event)),
                            label: "自动更新订阅",
                            color: "primary",
                            inset: "",
                            density: "compact",
                            hint: "定期自动更新 Clash 订阅配置"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_v_row, null, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_col, { cols: "12" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_text_field, {
                            modelValue: config.movie_pilot_url,
                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.movie_pilot_url) = $event)),
                            label: "MoviePilot URL",
                            variant: "outlined",
                            placeholder: "http://localhost:3001",
                            hint: "MoviePilot 服务的访问地址",
                            rules: [v => !!v || 'MoviePilot URL不能为空', v => isValidUrl(v) || '请输入有效的URL地址']
                          }, {
                            "prepend-inner": _withCtx(() => [
                              _createVNode(_component_v_icon, { color: "success" }, {
                                default: _withCtx(() => _cache[34] || (_cache[34] = [
                                  _createTextVNode("mdi-movie")
                                ])),
                                _: 1
                              })
                            ]),
                            _: 1
                          }, 8, ["modelValue", "rules"])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_v_tabs, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((activeTab).value = $event)),
                    class: "mt-4",
                    grow: ""
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_tab, { value: "subscription" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[35] || (_cache[35] = [
                              _createTextVNode("mdi-link-variant")
                            ])),
                            _: 1
                          }),
                          _cache[36] || (_cache[36] = _createTextVNode(" 订阅链接配置 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, { value: "clash" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[37] || (_cache[37] = [
                              _createTextVNode("mdi-application-brackets")
                            ])),
                            _: 1
                          }),
                          _cache[38] || (_cache[38] = _createTextVNode(" Clash 面板配置 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, { value: "execution" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[39] || (_cache[39] = [
                              _createTextVNode("mdi-play-circle")
                            ])),
                            _: 1
                          }),
                          _cache[40] || (_cache[40] = _createTextVNode(" 执行设置 "))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"]),
                  _createVNode(_component_v_divider),
                  _createVNode(_component_v_window, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((activeTab).value = $event)),
                    class: "pa-4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_window_item, { value: "subscription" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_row, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "3"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_switch, {
                                    modelValue: config.discard_rules,
                                    "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.discard_rules) = $event)),
                                    label: "丢弃订阅规则",
                                    color: "primary",
                                    inset: "",
                                    hint: "不保留订阅配置文件的'rules'字段"
                                  }, null, 8, ["modelValue"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "3"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_switch, {
                                    modelValue: config.discard_proxy_groups,
                                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.discard_proxy_groups) = $event)),
                                    label: "丢弃订阅代理组",
                                    color: "primary",
                                    inset: "",
                                    hint: "不保留订阅配置文件的'proxy-groups'字段"
                                  }, null, 8, ["modelValue"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "3"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_switch, {
                                    modelValue: config.group_by_country,
                                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.group_by_country) = $event)),
                                    label: "按国家分组节点",
                                    color: "primary",
                                    inset: "",
                                    hint: "启用后，根据名称将节点添加到代理组"
                                  }, null, 8, ["modelValue"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "3"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_switch, {
                                    modelValue: config.group_by_region,
                                    "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.group_by_region) = $event)),
                                    label: "按大洲分组节点",
                                    color: "primary",
                                    inset: "",
                                    hint: "启用后，根据名称将节点添加到代理组"
                                  }, null, 8, ["modelValue"])
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_row, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_col, { cols: "12" }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_combobox, {
                                    modelValue: config.sub_links,
                                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.sub_links) = $event)),
                                    label: "订阅链接",
                                    variant: "outlined",
                                    multiple: "",
                                    chips: "",
                                    "closable-chips": "",
                                    hint: "添加 Clash | V2Ray 订阅链接. 为避免冲突, 只有第一个链接的代理组会被保留",
                                    rules: [validateSubLinks]
                                  }, {
                                    chip: _withCtx(({ props, item }) => [
                                      _createVNode(_component_v_chip, _mergeProps(props, {
                                        closable: "",
                                        size: "small"
                                      }), {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(extractDomain(item.value)), 1)
                                        ]),
                                        _: 2
                                      }, 1040)
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue", "rules"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, { cols: "12" }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_combobox, {
                                    modelValue: config.filter_keywords,
                                    "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.filter_keywords) = $event)),
                                    label: "节点过滤关键词",
                                    variant: "outlined",
                                    multiple: "",
                                    chips: "",
                                    "closable-chips": "",
                                    clearable: "",
                                    hint: "添加用于过滤节点的关键词"
                                  }, {
                                    chip: _withCtx(({ props, item }) => [
                                      _createVNode(_component_v_chip, _mergeProps(props, {
                                        closable: "",
                                        size: "small",
                                        color: "info"
                                      }), {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(item.value), 1)
                                        ]),
                                        _: 2
                                      }, 1040)
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue"])
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, { value: "clash" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_row, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_col, { cols: "12" }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_text_field, {
                                    modelValue: config.clash_dashboard_url,
                                    "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.clash_dashboard_url) = $event)),
                                    label: "Clash 面板 URL",
                                    variant: "outlined",
                                    placeholder: "http://localhost:9090",
                                    hint: "Clash 控制面板的访问地址",
                                    rules: [v => !v || isValidUrl(v) || '请输入有效的URL地址']
                                  }, {
                                    "prepend-inner": _withCtx(() => [
                                      _createVNode(_component_v_icon, { color: "primary" }, {
                                        default: _withCtx(() => _cache[41] || (_cache[41] = [
                                          _createTextVNode("mdi-web")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue", "rules"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "6"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_text_field, {
                                    modelValue: config.clash_dashboard_secret,
                                    "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.clash_dashboard_secret) = $event)),
                                    label: "Clash 面板密钥",
                                    variant: "outlined",
                                    placeholder: "your-clash-secret",
                                    hint: "用于访问Clash API的密钥",
                                    "append-inner-icon": showClashSecret.value ? 'mdi-eye-off' : 'mdi-eye',
                                    type: showClashSecret.value ? 'text' : 'password',
                                    "onClick:appendInner": _cache[14] || (_cache[14] = $event => (showClashSecret.value = !showClashSecret.value))
                                  }, {
                                    "prepend-inner": _withCtx(() => [
                                      _createVNode(_component_v_icon, { color: "warning" }, {
                                        default: _withCtx(() => _cache[42] || (_cache[42] = [
                                          _createTextVNode("mdi-key")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue", "append-inner-icon", "type"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "6"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_select, {
                                    modelValue: config.dashboard_components,
                                    "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.dashboard_components) = $event)),
                                    items: dashboardComponents,
                                    label: "仪表盘组件",
                                    "hide-details": "",
                                    variant: "outlined",
                                    multiple: "",
                                    chips: "",
                                    class: "mb-4",
                                    hint: "添加仪表盘组件"
                                  }, {
                                    "prepend-inner": _withCtx(() => [
                                      _createVNode(_component_v_icon, { color: "info" }, {
                                        default: _withCtx(() => _cache[43] || (_cache[43] = [
                                          _createTextVNode("mdi-view-dashboard")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue"])
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, { value: "execution" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_row, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "4"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_cron_field, {
                                    modelValue: config.cron_string,
                                    "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((config.cron_string) = $event)),
                                    label: "执行周期",
                                    placeholder: "0 4 * * *",
                                    hint: "使用标准Cron表达式格式 (分 时 日 月 周)"
                                  }, {
                                    "prepend-inner": _withCtx(() => [
                                      _createVNode(_component_v_icon, { color: "info" }, {
                                        default: _withCtx(() => _cache[44] || (_cache[44] = [
                                          _createTextVNode("mdi-clock-time-four-outline")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "4"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_text_field, {
                                    modelValue: config.timeout,
                                    "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.timeout) = $event)),
                                    modelModifiers: { number: true },
                                    label: "超时时间",
                                    variant: "outlined",
                                    type: "number",
                                    min: "1",
                                    max: "300",
                                    suffix: "秒",
                                    hint: "请求的超时时间",
                                    rules: [v => v > 0 || '超时时间必须大于0']
                                  }, null, 8, ["modelValue", "rules"])
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "4"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_text_field, {
                                    modelValue: config.retry_times,
                                    "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((config.retry_times) = $event)),
                                    modelModifiers: { number: true },
                                    label: "重试次数",
                                    variant: "outlined",
                                    type: "number",
                                    min: "0",
                                    max: "10",
                                    hint: "失败时的重试次数",
                                    rules: [v => v >= 0 || '重试次数不能为负数']
                                  }, {
                                    "prepend-inner": _withCtx(() => [
                                      _createVNode(_component_v_icon, { color: "info" }, {
                                        default: _withCtx(() => _cache[45] || (_cache[45] = [
                                          _createTextVNode("mdi-refresh")
                                        ])),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }, 8, ["modelValue", "rules"])
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"]),
                  _createVNode(_component_v_expansion_panels, {
                    variant: "accordion",
                    class: "mt-4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_expansion_panel, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_expansion_panel_title, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, { class: "mr-2" }, {
                                default: _withCtx(() => _cache[46] || (_cache[46] = [
                                  _createTextVNode("mdi-cog")
                                ])),
                                _: 1
                              }),
                              _cache[47] || (_cache[47] = _createTextVNode(" 高级选项 "))
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_expansion_panel_text, null, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_row, null, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "4"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_switch, {
                                        modelValue: config.hint_geo_dat,
                                        "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((config.hint_geo_dat) = $event)),
                                        label: "Geo规则补全",
                                        color: "primary",
                                        inset: "",
                                        hint: "获取官方Geo数据库, 并在输入时补全"
                                      }, null, 8, ["modelValue"])
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "4"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_switch, {
                                        modelValue: config.enable_acl4ssr,
                                        "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((config.enable_acl4ssr) = $event)),
                                        label: "ACL4SSR规则集",
                                        color: "primary",
                                        inset: "",
                                        hint: "启用ACL4SSR规则集"
                                      }, null, 8, ["modelValue"])
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "4",
                                    class: "d-flex align-end"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_btn, {
                                        color: "primary",
                                        onClick: openClashTemplateDialog,
                                        block: ""
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_icon, { left: "" }, {
                                            default: _withCtx(() => _cache[48] || (_cache[48] = [
                                              _createTextVNode("mdi-import")
                                            ])),
                                            _: 1
                                          }),
                                          _cache[49] || (_cache[49] = _createTextVNode(" Clash 配置模板 "))
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_row, null, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "4"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_text_field, {
                                        modelValue: config.ruleset_prefix,
                                        "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((config.ruleset_prefix) = $event)),
                                        label: "规则集前缀",
                                        variant: "outlined",
                                        placeholder: "📂<=",
                                        rules: [v => !!v || '规则集前缀不能为空'],
                                        hint: "为生成的规则集添加前缀"
                                      }, {
                                        "prepend-inner": _withCtx(() => [
                                          _createVNode(_component_v_icon, { color: "info" }, {
                                            default: _withCtx(() => _cache[50] || (_cache[50] = [
                                              _createTextVNode("mdi-palette")
                                            ])),
                                            _: 1
                                          })
                                        ]),
                                        _: 1
                                      }, 8, ["modelValue", "rules"])
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "4"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_text_field, {
                                        modelValue: config.acl4ssr_prefix,
                                        "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((config.acl4ssr_prefix) = $event)),
                                        label: "ACL4SSR 规则集前缀",
                                        variant: "outlined",
                                        placeholder: "🗂️=>",
                                        rules: [v => !!v || '规则集前缀不能为空'],
                                        hint: "ACL4SSR 规则集前缀"
                                      }, {
                                        "prepend-inner": _withCtx(() => [
                                          _createVNode(_component_v_icon, { color: "primary" }, {
                                            default: _withCtx(() => _cache[51] || (_cache[51] = [
                                              _createTextVNode("mdi-palette")
                                            ])),
                                            _: 1
                                          })
                                        ]),
                                        _: 1
                                      }, 8, ["modelValue", "rules"])
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "4"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_text_field, {
                                        modelValue: config.refresh_delay,
                                        "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((config.refresh_delay) = $event)),
                                        modelModifiers: { number: true },
                                        label: "刷新延迟",
                                        variant: "outlined",
                                        type: "number",
                                        min: "1",
                                        max: "30",
                                        suffix: "秒",
                                        hint: "通知Clash刷新规则集的延迟时间",
                                        rules: [v => v >= 0 || '刷新延迟不能为负数']
                                      }, {
                                        "prepend-inner": _withCtx(() => [
                                          _createVNode(_component_v_icon, { color: "info" }, {
                                            default: _withCtx(() => _cache[52] || (_cache[52] = [
                                              _createTextVNode("mdi-clock-outline")
                                            ])),
                                            _: 1
                                          })
                                        ]),
                                        _: 1
                                      }, 8, ["modelValue", "rules"])
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }),
                              _createVNode(_component_v_row, null, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_col, {
                                    cols: "12",
                                    md: "12"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_combobox, {
                                        modelValue: config.best_cf_ip,
                                        "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((config.best_cf_ip) = $event)),
                                        label: "Cloudflare CDN 优选 IPs",
                                        variant: "outlined",
                                        multiple: "",
                                        chips: "",
                                        "closable-chips": "",
                                        clearable: "",
                                        hint: "用于设置 Hosts 中的 Cloudflare 域名",
                                        rules: [validateIPs]
                                      }, {
                                        chip: _withCtx(({ props, item }) => [
                                          _createVNode(_component_v_chip, _mergeProps(props, {
                                            closable: "",
                                            size: "small"
                                          }), {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(item.value), 1)
                                            ]),
                                            _: 2
                                          }, 1040)
                                        ]),
                                        _: 1
                                      }, 8, ["modelValue", "rules"])
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }, 8, ["modelValue"])
            ]),
            _: 1
          }),
          _createVNode(_component_v_alert, {
            type: "info",
            text: "",
            variant: "tonal"
          }, {
            default: _withCtx(() => _cache[53] || (_cache[53] = [
              _createTextVNode(" 配置说明参考: "),
              _createElementVNode("a", {
                href: "https://github.com/wumode/MoviePilot-Plugins/tree/main/plugins.v2/clashruleprovider/README.md",
                target: "_blank"
              }, "README", -1)
            ])),
            _: 1
          }),
          _createVNode(_component_v_card_actions, null, {
            default: _withCtx(() => [
              _createVNode(_component_v_btn, {
                color: "primary",
                onClick: notifySwitch
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, { left: "" }, {
                    default: _withCtx(() => _cache[54] || (_cache[54] = [
                      _createTextVNode("mdi-view-dashboard-edit")
                    ])),
                    _: 1
                  }),
                  _cache[55] || (_cache[55] = _createTextVNode(" 规则 "))
                ]),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                color: "secondary",
                onClick: resetForm
              }, {
                default: _withCtx(() => _cache[56] || (_cache[56] = [
                  _createTextVNode("重置")
                ])),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                color: "info",
                onClick: testConnection,
                loading: testing.value
              }, {
                default: _withCtx(() => _cache[57] || (_cache[57] = [
                  _createTextVNode("测试连接")
                ])),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_v_spacer),
              _createVNode(_component_v_btn, {
                color: "primary",
                disabled: !isFormValid.value,
                onClick: saveConfig,
                loading: saving.value
              }, {
                default: _withCtx(() => _cache[58] || (_cache[58] = [
                  _createTextVNode(" 保存配置 ")
                ])),
                _: 1
              }, 8, ["disabled", "loading"])
            ]),
            _: 1
          }),
          (testResult.show)
            ? (_openBlock(), _createBlock(_component_v_alert, {
                key: 0,
                type: testResult.success ? 'success' : 'error',
                variant: "tonal",
                closable: "",
                class: "ma-4 mt-0",
                "onClick:close": _cache[27] || (_cache[27] = $event => (testResult.show = false))
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_2, [
                    _createVNode(_component_v_icon, { class: "mr-2" }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(testResult.success ? 'mdi-check-circle' : 'mdi-alert-circle'), 1)
                      ]),
                      _: 1
                    }),
                    _createElementVNode("div", null, [
                      _createElementVNode("div", _hoisted_3, _toDisplayString(testResult.title), 1),
                      _createElementVNode("div", _hoisted_4, _toDisplayString(testResult.message), 1)
                    ])
                  ])
                ]),
                _: 1
              }, 8, ["type"]))
            : _createCommentVNode("", true)
        ]),
        _: 1
      })
    ]),
    _createVNode(_component_v_dialog, {
      modelValue: clashTemplateDialog.value,
      "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((clashTemplateDialog).value = $event)),
      "max-width": "600"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => _cache[59] || (_cache[59] = [
                _createTextVNode("Clash 配置模板")
              ])),
              _: 1
            }),
            _createVNode(_component_v_card_text, { style: {"max-height":"900px","overflow-y":"auto"} }, {
              default: _withCtx(() => [
                _createVNode(_component_v_select, {
                  modelValue: clashTemplateType.value,
                  "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((clashTemplateType).value = $event)),
                  items: ['YAML'],
                  label: "配置类型",
                  class: "mb-4"
                }, null, 8, ["modelValue"]),
                _createVNode(_unref(VAceEditor), {
                  value: clashTemplateContent.value,
                  "onUpdate:value": _cache[29] || (_cache[29] = $event => ((clashTemplateContent).value = $event)),
                  lang: "yaml",
                  theme: "monokai",
                  hint: "",
                  options: editorOptions,
                  placeholder: configPlaceholder.value,
                  style: {"height":"30rem","width":"100%","margin-bottom":"16px"}
                }, null, 8, ["value", "placeholder"]),
                _createVNode(_component_v_alert, {
                  type: "info",
                  dense: "",
                  text: "",
                  class: "mb-4",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => _cache[60] || (_cache[60] = [
                    _createTextVNode("规则和出站代理会被添加在配置模板上 ")
                  ])),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  text: "",
                  onClick: _cache[30] || (_cache[30] = $event => (clashTemplateDialog.value = false))
                }, {
                  default: _withCtx(() => _cache[61] || (_cache[61] = [
                    _createTextVNode("取消")
                  ])),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "primary",
                  onClick: saveClashTemplate
                }, {
                  default: _withCtx(() => _cache[62] || (_cache[62] = [
                    _createTextVNode("确定")
                  ])),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ], 64))
}
}

};
const ConfigComponent = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c2db3dad"]]);

export { ConfigComponent as default };
