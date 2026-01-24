# 如何在 AutoSports 插件中添加自定义赛事？
首先在插件设置中打开 `自定义赛事元数据`\
在弹出的输入框按下面的格式进行赛事自定义：
> - 插件已内置五大联赛+欧冠+国王杯+西超杯，请勿重复配置，特别要注意 `shortname` 字段不要与已有的重复，已有的是 `PD、CL、CDR、SE、PL、SA、BL1、FL1、`\
> - 注意无关内容需使用 // 注释，但行内不要使用 // 注释\
> - 只有标注【必填】的字段是必须有的，其它可以省略\
> - 必须严格遵循 json 格式，即每个 json 的最后一个字段后面不要有逗号\
> - 多个赛事就是多个 json 的列表\
```json lines
[{
    // 示例一：在 football-data.org 有数据的联赛或杯赛（在线刮削）
    // 【必填】别名（区分大小写）
    "names": ["EPL"], 
    // 【必填】赛事类型（联赛：LEAGUE/杯赛：CUP）
    "type": "LEAGUE", 
    // 【在线刮削必填】缩写 (需要与 football.org 上的缩写对应)
    "shortname": "PL",
    // 【必填】中文名
    "title": "英格兰足球超级联赛",
    // 英文名
    "en_title": "La Liga", 
    // 原名
    "original_title": "La Liga",  
    // 创办年份
    "year": 1929, 
    // 赛事简介
    "overview": "赛事简介",
    // 官网
    "homepage": "www.laliga.com", 
    // 解说源语言
    "languages": ["Spanish"], 
    // 国家
    "origin_country": "Spain",  
    // 原名
    "original_name": "Primera División de España", 
    // 创办协会
    "production_companies": ["西班牙皇家足球协会 (RFEF)"],  
    // 国家
    "production_countries": ["Spain"], 
    // 语言
    "spoken_languages": ["Spanish"],  
    // 比赛时长
    "runtime": 9000,
    // 【离线刮削必填】本地刮削信息（空表示 football.org 上提供该赛事信息，不进行本地刮削)
    "offline_info": {}
}, 
{
    // 示例二：在football-data.org 没有数据的杯赛（离线刮削）
    // 【必填】别名（区分大小写）
    "names": ["西班牙国王杯", "Copa Del Rey", "Campeonato de España – Copa de Su Majestad el Rey", "国王杯"], 
    // 【必填】赛事类型（联赛：LEAGUE/杯赛：CUP）
    "type": "CUP", 
    // 缩写
    "shortname": "CDR",
    // 【必填】中文名
    "title": "西班牙国王杯",
    // 英文名
    "en_title": "Copa Del Rey", 
    // 原名
    "original_title": "Copa Del Rey",  
    // 创办年份
    "year": 1903, 
    // 赛事简介
    "overview": "赛事简介",
    // 官网
    "homepage": "www.laliga.com/en-GB/other-competitions/copa-del-rey", 
    // 解说源语言
    "languages": ["Spanish"], 
    // 国家
    "origin_country": "Spain",  
    // 原名
    "original_name": "Primera División de España", 
    // 创办协会
    "production_companies": ["西班牙皇家足球协会 (RFEF)"],  
    // 国家
    "production_countries": ["Spain"], 
    // 语言
    "spoken_languages": ["Spanish"],  
    // 比赛时长
    "runtime": 9000,
    // 【必填】
    "offline_info": {
         // 【必填】 小组赛比赛场次
         "group": 0,  
         // 【必填】 单场淘汰赛起始轮次（例如 32 表示从 32 进 16 这一轮开始），0 表示没有
         "knockout_single": 32,
         // 【必填】 主客场淘汰赛起始轮次（例如 32 表示从 32 进 16 这一轮开始），0 表示没有
         "knockout_double": 4
    }
}]
```