from html import escape as html_escape
import math
from typing import Any, List, Dict, Tuple


from app import schemas
from app.sdk.config import settings
from app.sdk.services import DownloaderHelper

from app.plugins.autosports.recognition.competitions import get_demo_competitions_config


def _crest_html(url: str = "") -> str:
    """
    生成固定 20px 的 crest 图片片段，用于插件数据页的赛事/球队图标。

    :param url: 图片地址
    :return: 可直接放进插槽的 HTML 片段，地址为空时返回空字符串
    """
    if not url:
        return ""
    return (
        f'<img src="{html_escape(url, quote=True)}" alt="" '
        'style="width:20px;height:20px;object-fit:contain;display:block;" />'
    )

def _team_row(name: str, crest_url: str = "") -> dict:
    """
    生成“球队 crest + 加粗队名”的一行页面组件。

    :param name: 球队名称
    :param crest_url: 球队 crest 图片地址，为空时只显示队名
    :return: 页面组件配置
    """
    content = []
    crest = _crest_html(crest_url)
    if crest:
        content.append({
            'component': 'div',
            'props': {'class': 'me-2 d-flex align-center flex-shrink-0'},
            'html': crest,
        })
    content.append({
        'component': 'span',
        'props': {'class': 'text-body-1 font-weight-bold'},
        'text': name,
    })
    return {
        'component': 'div',
        'props': {'class': 'd-flex align-center justify-center'},
        'content': content,
    }

class Ui:

    """AutoSports ui 相关方法。"""

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'dialog_opened',
                                            'label': '自定义赛事元数据',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'proxy',
                                            'label': '使用代理服务器',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'filter',
                                            'label': '(暂不支持)订阅优先级规则',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'filter_builtin_search',
                                            'label': '内置搜索也按过滤规则筛选本站种子',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'need_rename',
                                            'label': '是否开启自动重命名',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'force_en',
                                            'label': '是否只下载英文解说版本',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'start_paused',
                                            'label': '以暂停状态添加种子',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'sync_all',
                                            'label': '是否进行下载目录全量扫描整理',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clear',
                                            'label': '清理历史记录（保存后生效）',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动，设定的运行时间间隔不要小于1h'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'action',
                                            'label': '运行模式',
                                            'items': [
                                                {'title': '下载+整理（默认）', 'value': 'download'},
                                                {'title': '仅（全量）整理', 'value': 'transfer'},
                                                {'title': '订阅（暂不支持）', 'value': 'subscribe'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'monitor_mode',
                                            'label': '目录监控模式',
                                            'items': [
                                                {'title': '普通模式（性能更好）', 'value': 'normal'},
                                                {'title': '兼容模式（远程/SMB）', 'value': 'compatibility'},
                                            ],
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    # 'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'football_apikey',
                                            'label': '比赛元数据 API key (请前往 football-data.org 自行获取)',
                                            'rows': 3,
                                            'placeholder': '请输入 football-data.org 上有效的 API key'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'teams_info',
                                            'label': '球队名关键词（英文），只支持单球队，一行一个',
                                            'rows': 3,
                                            'placeholder': 'Barcelona'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'max_download',
                                            'label': '单次运行最大下载比赛场数',
                                            'rows': 3,
                                            'placeholder': '3'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'include',
                                            'label': '包含',
                                            'placeholder': '支持正则表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude',
                                            'label': '排除',
                                            'placeholder': '支持正则表达式'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size_range',
                                            'label': '种子大小(GB)',
                                            'placeholder': '如：3 或 3-5'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'lowest_pix',
                                            'label': '最低清晰度(p)，请输入整数',
                                            'placeholder': '如：720'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category',
                                            'label': '种子分类，留空为不设置',
                                            'placeholder': '如：Sports'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tags',
                                            'label': '种子除AutoSports外的额外标签，逗号分隔',
                                            'placeholder': '如：Match,Football'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [
                                                {"title": config.name, "value": config.name} for config in DownloaderHelper().get_configs().values()
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'transfer_type',
                                            'label': '转移方式',
                                            'items': [
                                                {'title': '移动', 'value': 'move'},
                                                {'title': '复制', 'value': 'copy'},
                                                {'title': '硬链接', 'value': 'link'},
                                                {'title': '软链接', 'value': 'softlink'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'save_path',
                                            'label': '下载目录',
                                            'placeholder': '必须是设置中已添加的目录设置的子集'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'dest_path',
                                            'label': '转移目录',
                                            'placeholder': '必须是设置中已添加的目录设置的子集'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        "component": "VDialog",
                        "props": {
                            "model": "dialog_opened",
                            "max-width": "65rem",
                            "overlay-class": "v-dialog--scrollable v-overlay--scroll-blocked",
                            "content-class": "v-card v-card--density-default v-card--variant-elevated rounded-t"
                        },
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "title": "设置自定义赛事"
                                },
                                "content": [
                                    {
                                        "component": "VDialogCloseBtn",
                                        "props": {
                                            "model": "dialog_opened"
                                        }
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {},
                                        "content": [
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VAceEditor',
                                                                'props': {
                                                                    'modelvalue': 'competitions_config',
                                                                    'lang': 'json',
                                                                    'theme': 'monokai',
                                                                    'style': 'height: 30rem',
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VAlert',
                                                                'props': {
                                                                    'type': 'info',
                                                                    'variant': 'tonal'
                                                                },
                                                                'content': [
                                                                    {
                                                                        'component': 'span',
                                                                        'text': '该配置可以在插件内已有元数据的基础上新增自定义扩展，配置规则请参考：'
                                                                    },
                                                                    {
                                                                        'component': 'a',
                                                                        'props': {
                                                                            'href': 'https://github.com/Sinterdial/MoviePilot-Plugins/blob/main/docs/Self_Defined_Competitions_Guide.md',
                                                                            'target': '_blank'
                                                                        },
                                                                        'content': [
                                                                            {
                                                                                'component': 'u',
                                                                                'text': 'README'
                                                                            }
                                                                        ]
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "football_apikey": "",
            "teams_info": "",
            "notify": True,
            "onlyonce": False,
            "cron": "27 6-8 * * *",
            "include": "",
            "exclude": "",
            "proxy": False,
            "clear": False,
            "filter": False,
            "filter_builtin_search": False,
            "action": "download",
            "save_path": "",
            "dest_path": "",
            "category": "",
            "tags": [],
            "size_range": "",
            "force_en": False,
            "lowest_px": "720",
            "transfer_type": "link",
            "need_rename": True,
            "max_download": 3,
            "start_paused": True,
            "competitions_config": get_demo_competitions_config(),
            "monitor_mode": "normal",
            "sync_all": False
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        histories = self.get_data('history')
        if not histories:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        # 数据按时间降序排序
        histories = sorted(histories, key=lambda x: x.get('time'), reverse=True)
        # 分页展示，避免历史记录过多导致插件页面卡顿
        total_pages = max(1, math.ceil(len(histories) / self._HISTORY_PAGE_SIZE))
        current_page = min(max(self._history_page or 1, 1), total_pages)
        self._history_page = current_page
        start = (current_page - 1) * self._HISTORY_PAGE_SIZE
        page_histories = histories[start:start + self._HISTORY_PAGE_SIZE]
        # 拼装页面
        contents = []
        for history in page_histories:
            competition_name = history.get("competition_name")
            roundinfo = history.get("roundinfo")
            round_cn_name = history.get("round_cn_name")
            matchmake = history.get("matchmake")
            time_str = history.get("time")
            # 赛事 logo 和赛事名同高，队名前的 crest 也保持同样尺寸
            logo_html = _crest_html(self._competition_logo(competition_name))
            # 对阵拆成两个队名，方便加粗突出显示
            home_team_name, away_team_name = matchmake or "", ""
            if " vs " in home_team_name:
                home_team_name, away_team_name = home_team_name.split(" vs ", 1)
            home_crest, away_crest = self._match_crest_pair(matchmake)
            # 历史记录里存了球队 crest 时优先用记录里的，旧记录则回退到内存缓存
            home_crest = history.get("home_crest") or home_crest
            away_crest = history.get("away_crest") or away_crest
            contents.append(
                {
                    'component': 'VCard',
                    'props': {
                        'class': 'pa-2',
                    },
                    'content': [
                        {
                            "component": "VDialogCloseBtn",
                            "props": {
                                'innerClass': 'absolute top-0 right-0',
                            },
                            'events': {
                                'click': {
                                    'api': 'plugin/AutoSports/delete_history',
                                    'method': 'get',
                                    'params': {
                                        'key': competition_name,
                                        'roundinfo': roundinfo,
                                        'apikey': settings.API_TOKEN,
                                    }
                                }
                            },
                        },
                        {
                            'component': 'div',
                            'props': {
                                'class': 'd-flex flex-column px-2 pe-8',
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'props': {
                                        'class': 'd-flex align-center',
                                    },
                                    'content': [
                                        *([{
                                            'component': 'div',
                                            'props': {
                                                'class': 'me-2 d-flex align-center flex-shrink-0',
                                            },
                                            'html': logo_html,
                                        }] if logo_html else []),
                                        {
                                            'component': 'div',
                                            'props': {
                                                'class': 'text-h6 font-weight-bold text-truncate',
                                                'style': 'min-width: 0;',
                                            },
                                            'text': competition_name or '',
                                        },
                                    ],
                                },
                                # 只展示轮次值，不再显示“轮次”两个字
                                *([{
                                    'component': 'div',
                                    'props': {
                                        'class': 'text-body-2 text-medium-emphasis mt-1',
                                    },
                                    'text': round_cn_name,
                                }] if round_cn_name else []),
                                # 对阵分三行：主队、VS 分隔、客队，双方加粗并带球队 logo
                                {
                                    'component': 'div',
                                    'props': {
                                        'class': 'd-flex flex-column mt-2',
                                    },
                                    'content': [
                                        _team_row(home_team_name, home_crest),
                                        *([{
                                            'component': 'div',
                                            'props': {
                                                'class': 'd-flex align-center my-1',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'props': {
                                                        'class': 'flex-grow-1',
                                                        'style': 'border-top: 1px solid rgba(128, 128, 128, 0.35);',
                                                    },
                                                },
                                                {
                                                    'component': 'span',
                                                    'props': {
                                                        'class': 'text-caption text-medium-emphasis mx-2',
                                                    },
                                                    'text': 'VS',
                                                },
                                                {
                                                    'component': 'div',
                                                    'props': {
                                                        'class': 'flex-grow-1',
                                                        'style': 'border-top: 1px solid rgba(128, 128, 128, 0.35);',
                                                    },
                                                },
                                            ],
                                        },
                                        _team_row(away_team_name, away_crest)] if away_team_name else []),
                                    ],
                                },
                                # 处理时间标签和值各占一行，右对齐
                                {
                                    'component': 'div',
                                    'props': {
                                        'class': 'text-caption text-medium-emphasis mt-2 text-right',
                                    },
                                    'text': '处理时间',
                                },
                                {
                                    'component': 'div',
                                    'props': {
                                        'class': 'text-body-2 text-right',
                                    },
                                    'text': time_str or '-',
                                },
                            ],
                        },
                    ],
                }
            )

        if total_pages > 1:
            contents.append({
                'component': 'div',
                'props': {
                    'class': 'd-flex align-center justify-center ga-4 mt-2',
                },
                'content': [
                    {
                        'component': 'VBtn',
                        'text': '上一页',
                        'props': {'variant': 'text', 'disabled': current_page <= 1},
                        'events': {
                            'click': {
                                'api': 'plugin/AutoSports/history_page',
                                'method': 'get',
                                'params': {'direction': 'prev', 'apikey': settings.API_TOKEN},
                            }
                        },
                    },
                    {
                        'component': 'span',
                        'text': f'第 {current_page} / {total_pages} 页，共 {len(histories)} 条',
                    },
                    {
                        'component': 'VBtn',
                        'text': '下一页',
                        'props': {'variant': 'text', 'disabled': current_page >= total_pages},
                        'events': {
                            'click': {
                                'api': 'plugin/AutoSports/history_page',
                                'method': 'get',
                                'params': {'direction': 'next', 'apikey': settings.API_TOKEN},
                            }
                        },
                    },
                ],
            })

        return [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            }
        ]

    def delete_history(self, key: str, roundinfo: str, apikey: str):
        """
        删除同步历史记录
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        # 历史记录
        histories = self.get_data('history')
        if not histories:
            return schemas.Response(success=False, message="未找到历史记录")
        # 删除指定记录
        histories = [h for h in histories if (
            h.get("competition_name") != key or h.get("roundinfo") != roundinfo)]
        self.save_data('history', histories)
        return schemas.Response(success=True, message="删除成功")

    def history_page(self, direction: str = "next", apikey: str = ""):
        """
        翻页查看同步历史记录。

        :param direction: 翻页方向，prev 上一页 / next 下一页
        :param apikey: 插件 API 密钥
        :return: 翻页结果
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        histories = self.get_data('history') or []
        total_pages = max(1, math.ceil(len(histories) / self._HISTORY_PAGE_SIZE))
        page = self._history_page or 1
        if direction == "prev":
            page -= 1
        elif direction == "next":
            page += 1
        self._history_page = min(max(page, 1), total_pages)
        return schemas.Response(success=True, message=f"第 {self._history_page} / {total_pages} 页")
