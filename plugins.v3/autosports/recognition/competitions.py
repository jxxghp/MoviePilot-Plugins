import json


# 内置赛事的官方 logo（football-data.org 队徽图床），自定义赛事可在配置里用 logo 字段覆盖
_COMPETITION_LOGOS = {
    "PD": "https://crests.football-data.org/laliga.png",
    "CL": "https://crests.football-data.org/CL.png",
    "PL": "https://crests.football-data.org/PL.png",
    "SA": "https://crests.football-data.org/c111.png",
    "BL1": "https://crests.football-data.org/BL1.png",
    "FL1": "https://crests.football-data.org/FL1.png",
}

def get_raw_competitions_parse() -> list[dict]:
    return [
        {
            "names": ["西甲", "La Liga", "LaLiga", "Laliga", "西班牙足球甲级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "PD",  # 缩写
            "title": "西班牙足球甲级联赛",  # 中文名
            "en_title": "La Liga",  # 英文名
            "original_title": "La Liga",  # 原名
            "year": 1929,  # 创办年份
            "overview": "西班牙足球甲级联赛（西班牙语：Primera División de España或La Liga，由于赞助原因，正式名称为LALIGA EA SPORTS），通常简称西甲或西甲联赛，是西班牙足球联赛系统的第 1 级别，亦是职业联赛的最高级别、联赛系统的最高级别和西班牙顶级足球联赛，目前有 20 支球队。皇家马德里是历史上夺得最多冠军的球队（36次），其次是巴塞罗那（28次），以及马德里竞技（11次）。 ",  # 赛事介绍
            "season_years": {x: x for x in range(1929, 2101)},  # 赛季
            "homepage": "https://www.laliga.com",  # 官网
            "languages": ["Spanish"],  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": ["西班牙皇家足球协会 (RFEF)"],  # 创办协会
            "production_countries": ["Spain"],  # 国家
            "spoken_languages": ["Spanish"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["欧洲冠军联赛", "Champions League", "UCL", "UEFA Champions League", "UEFA"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "CL",  # 缩写
            "title": "欧洲冠军联赛",  # 中文名
            "en_title": "UEFA Champions League",  # 英文名
            "original_title": "UEFA Champions League",  # 原名
            "year": 1955,  # 创办年份
            "overview": "欧洲冠军联赛（英语：UEFA Champions League，缩写：UCL；简称欧冠联赛、欧冠）是欧洲足联主办的年度俱乐部足球比赛，该赛事由欧洲顶级联赛的俱乐部队伍参加，通过联赛阶段和双回合淘汰赛，以及单场决赛的形式决出冠军。代表欧洲俱乐部足球最高荣誉，被誉为全世界最高竞技水平的俱乐部杯赛，估计每届赛事约有超过十亿电视观众观看赛事，现与欧洲联赛和欧协联并称“欧洲俱乐部三大杯”。\n"
                        "欧洲冠军联赛始创于1955年，被称为“欧洲俱乐部冠军杯”（法语：Coupe des Clubs Champions Européens），通称欧洲冠军杯（英语：European Cup）。最初，该赛事以直接淘汰制形式进行，并仅对欧洲各国的联赛冠军开放。随后在1991年引入小组赛环节，并于1992年更为现名。自1997-98赛季起，部分国家可派出最多4支球队参赛。目前，大部分欧洲国家仅能派出其联赛冠军参赛，而实力较强的联赛最多可派出四支球队。未能晋级欧冠的俱乐部有资格参加欧洲联赛及自2021年起举办的欧洲协会联赛。\n"
                        "现行赛制从六月下旬开始，包括三轮资格赛和一轮附加赛，均采用双回合制。六支晋级球队进入联赛阶段，与提前获得资格的30支球队会合。36支球队会透过以瑞士制为基础的联赛模式定出晋级淘汰赛阶段的球队（在联赛阶段取得首八名的球队直接晋级，余下八队会经淘汰附加赛决定）最终在五月底或六月初的决赛中决出冠军。赛事冠军将自动获得参加下一年度欧洲冠军联赛、欧洲超级杯及俱乐部世界杯的参赛资格。\n"
                        "在欧冠历史上，西班牙俱乐部以20次冠军居于榜首，英格兰和意大利分别以15次和12次获胜紧随其后。英格兰拥有最多的获胜球队，共六家俱乐部赢得冠军。迄今为止，共有23家俱乐部夺冠，其中13家俱乐部多次夺冠，8家成功卫冕。皇家马德里是该赛事历史上最成功的俱乐部，共赢得了15次冠军，包括首五届赛事冠军和最近十一届中的六次。只有拜仁慕尼黑以全胜战绩（2019–20赛季）夺得冠军。",
            "season_years": {x: x for x in range(1955, 2101)},  # 赛季
            "homepage": "https://www.uefa.com",  # 官网
            "languages": ["English"],  # 解说源语言
            "origin_country": "Europa",  # 国家
            "original_name": "UEFA Champions League",  # 原名
            "production_companies": ["欧洲足球协会联盟 (UEFA)"],  # 创办协会
            "production_countries": ["Europa"],  # 国家
            "spoken_languages": ["English"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["西班牙国王杯", "Copa Del Rey", "Campeonato de España – Copa de Su Majestad el Rey", "国王杯"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "CDR",  # 缩写
            "title": "西班牙国王杯",  # 中文名
            "en_title": "Copa Del Rey",  # 英文名
            "original_title": "Copa Del Rey",  # 原名
            "year": 1903,  # 创办年份
            "overview": "西班牙冠军–国王陛下杯（西班牙语：Campeonato de España – Copa de Su Majestad el Rey），通称国王杯（Copa del Rey）或西班牙杯，是西班牙一项每年举办的淘汰制足球赛事。赛事开办起因于皇家马德里前主席卡洛斯·帕德罗斯提议举办一项足球赛事以庆祝西班牙国王阿方索十三世登基，而于1902年举行首届比赛。\n"
                        "赛事最早叫做“马德里市议会杯”（Copa del Ayuntamiento de Madrid），1905至1932年间称为“阿方索十三世杯”（Copa de S.M. El Rey Alfonso XIII），在西班牙第二共和国期间则称为“共和国总统杯”Copa del Presidente de la República），简称“西班牙杯” （Copa de España），在佛朗哥执政期间又改称为 “大元帅阁下杯”（Copa de Su Excelencia El Generalísimo） ，简称“大元帅杯”（Copa del Generalísimo)。",
            "season_years": {x: x for x in range(1903, 2101)},  # 赛季
            "homepage": "https://www.laliga.com/en-GB/other-competitions/copa-del-rey",  # 官网
            "languages": ["Spanish"],  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": ["西班牙皇家足球协会 (RFEF)"],  # 创办协会
            "production_countries": ["Spain"],  # 国家
            "spoken_languages": ["Spanish"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {  # 本地刮削信息（空表示不进行本地刮削）
                "group": 0,  # 小组赛比赛场次
                "knockout_single": 32,  # 单场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
                "knockout_double": 4  # 主客场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
            },
        },
        {
            "names": ["西班牙超级杯", "Supercopa de España", "Spanish Super Cup", "SuperCopa", "超级杯"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "SE",  # 缩写
            "title": "西班牙超级杯",  # 中文名
            "en_title": "Spanish Super Cup",  # 英文名
            "original_title": "Supercopa de España",  # 原名
            "year": 1982,  # 创办年份
            "overview": "西班牙超级杯（西班牙语：Supercopa de España）是西班牙每年一度由甲级联赛冠军对国王杯盟主的足球锦标赛，如果有一支球队同时夺得联赛及国王杯冠军，对赛球队则由国王杯亚军补上，2019年起增设联赛及国王杯亚军席位，如果有一支球队同时夺得联赛及国王杯冠亚军，对赛球队则由联赛排名较佳一方补上，改制成单场淘汰赛模式。首届赛事于1940年举行，作为每年球季开始前的揭幕战。\n"
                        "赛事早期曾经有过多个名称，首届赛事举行时名称为西班牙冠军杯（Copa de Campeones），但比赛直到1945年才又再举办，这时由于来自阿根廷的大使欲与西班牙打好友谊关系，遂以阿根廷金杯（Copa de Oro Argentina）为名举行比赛。1947年，为了庆祝胡安·裴隆成为阿根廷总统，而以其妻子伊娃·裴隆为名举行伊娃杯（Copa Eva Duarte）。可惜1953年之后球赛因为不受重视而停办，一直到1983年才又重新复办赛事，并正式将球赛命名为西班牙超级杯至今。",
            "season_years": {x: x for x in range(1982, 2101)},  # 赛季
            "homepage": "https://www.laliga.com/en-GB/other-competitions/supercopa-de-espana",  # 官网
            "languages": ["Spanish"],  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": ["西班牙皇家足球协会 (RFEF)"],  # 创办协会
            "production_countries": ["Spain"],  # 国家
            "spoken_languages": ["Spanish"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {  # 本地刮削信息（空表示不进行本地刮削）
                "group": 0,  # 小组赛比赛场次
                "knockout_single": 4,  # 单场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
                "knockout_double": 0  # 主客场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
            },

        },
        {
            "names": ["英超", "Premier League", "PremierLeague", "Premier league", "英格兰足球超级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "PL",  # 缩写
            "title": "英格兰足球超级联赛",  # 中文名
            "en_title": "Premier League",  # 英文名
            "original_title": "Premier League",  # 原名
            "year": 1992,  # 创办年份
            "overview": "英格兰足球超级联赛（英语：Premier League），通称“英超”，是英格兰足球最高等级的赛事类别亦是世上最顶级的足球联赛，由英格兰足球协会于1992年2月20日确立，首个赛季于1992–93年正式面世。作为英格兰足球联赛系统的组成部分，英超的每支球队均需与同级别的全部其它球队进行主客场制对赛。威尔士球队在英格兰足球联赛系统参赛，亦有资格成为英超球队，但不能再以威尔士国家地区身份参与欧洲赛事。\n"
                        "虽然英超是1992创立，但英格兰早在1888年就已经成立世界上最早的足球联赛，100多年来已有24队夺得顶级联赛的冠军(包含1992年以前的英甲时代与英超)，详细可参考英格兰足球联赛与英格兰足球冠军的页面。\n"
                        "英超共有20支参赛球队，运作模式为一所以20间俱乐部共同拥有的有限公司。赛季于每年8月至次年5月进行，每队共有38场比赛，20支球队相互对赛两次，其中主、客场各一次。每个赛季，英超共有380场比赛。大部分英超的比赛于周末下午开赛，亦有一部分在周中的傍晚举行。\n"
                        "英超是全世界最多人观看的体育联赛。在全球各地，212个地区有电视转播英超赛事，潜在观众约有47亿人。2014–15赛季，英超俱乐部的球场平均入场人数超过3.6万人，仅次于德国足球甲级联赛的4.35万人。 欧洲足联于2018年1月初发表一份126页的欧洲各大俱乐部统计报告，记录不同联赛与及俱乐部的数据。而于2016/2017赛季最多人入场联赛的统计中，英超以累积超过1300万人次入场成为第一。\n"
                        "自1992年成立以来，共有7队曾夺得联赛冠军，分别是曼联（13次）、曼城（8次）、切尔西（5次）、阿森纳（3次）、利物浦（2次）以及布莱克本流浪者和莱斯特城（各1次）。",  # 赛事介绍
            "season_years": {x: x for x in range(1992, 2101)},  # 赛季
            "homepage": "https://www.premierleague.com",  # 官网
            "languages": ["English"],  # 解说源语言
            "origin_country": "England",  # 国家
            "original_name": "Premier League",  # 原名
            "production_companies": ["英格兰足球协会 (The FA)"],  # 创办协会
            "production_countries": ["England"],  # 国家
            "spoken_languages": ["English"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["意甲", "Serie A", "SerieA", "serie A", "意大利足球甲级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "SA",  # 缩写
            "title": "意大利足球甲级联赛",  # 中文名
            "en_title": "Serie A",  # 英文名
            "original_title": "Scudetto",  # 原名
            "year": 1897,  # 创办年份
            "overview": "意大利足球甲级联赛（意大利语：Serie A，简称“意甲”），昵称“小盾牌”（意大利语：Scudetto，因为意甲卫冕冠军徽章外型类似盾牌），是意大利足球联赛系统的第 1 级别 ，亦是职业联赛的最高级别，联赛系统的最高级别和意大利顶级足球联赛，由意大利足球协会（Federazione Italiana Gioco Calcio，FIGC）所管理，意甲职业联盟（Lega Nazionale Professionisti Serie A，Lega Serie A）营运。尤文图斯是最成功的俱乐部，获得（36 次）冠军，其次是国际米兰（20 次）和AC米兰（19 次）。",  # 赛事介绍
            "season_years": {x: x for x in range(1897, 2101)},  # 赛季
            "homepage": "https://www.legaseriea.it",  # 官网
            "languages": ["Italian"],  # 解说源语言
            "origin_country": "Italy",  # 国家
            "original_name": "Scudetto",  # 原名
            "production_companies": ["意大利足球协会 (FIGC)"],  # 创办协会
            "production_countries": ["Italy"],  # 国家
            "spoken_languages": ["Italian"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["德甲", "Bundesliga", "bundesliga", "Fußball-Bundesliga", "德国足球甲级联赛", "足球联邦联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "BL1",  # 缩写
            "title": "德国足球甲级联赛",  # 中文名
            "en_title": "Bundesliga",  # 英文名
            "original_title": "Bundesliga",  # 原名
            "year": 1962,  # 创办年份
            "overview": "足球联邦联赛（德语：Fußball-Bundesliga，简称Bundesliga [ˈbʊndəsˌliːɡa]），中文通称为德国足球甲级联赛，或简称德甲，是德国足球最高等级的赛事类别，由德国足球协会于1962年7月28日在多特蒙德确立，自1963–64赛季面世。德甲的每支球队均需与同级别的全部其它球队进行主客场制对赛，最终的德国足球冠军可获得欧洲冠军联赛的参赛资格；而排名最末的两支球队将降级至德国足球乙级联赛（德乙）。排名倒数第三的球队则需要与德乙第三名进行保级附加赛，胜者可获准留在德甲。此外，所有德甲球队都可直接入围德国足协杯比赛，两者冠军将参加德国超级杯的争夺。\n"
                        "作为欧洲五大联赛之一，德甲在欧洲足联的联赛系数排名中目前位居全欧第4。德甲也是全球现场观战人数最高的足球联赛，其于2013年至2018年间的场均上座率高达43,302人次，同时还在全球209个国家和地区进行电视转播。拜仁慕尼黑是德甲最为成功的球队，共获得33次德国冠军。",  # 赛事介绍
            "season_years": {x: x for x in range(1962, 2101)},  # 赛季
            "homepage": "https://www.bundesliga.de",  # 官网
            "languages": ["German"],  # 解说源语言
            "origin_country": "Germany",  # 国家
            "original_name": "Fußball-Bundesliga",  # 原名
            "production_companies": ["德国足球协会 (DFB)"],  # 创办协会
            "production_countries": ["Germany"],  # 国家
            "spoken_languages": ["German"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["法甲", "Championnat de France de football", "Ligue 1", "Ligue1", "Ligue 1 McDonald's", "法国足球甲级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "FL1",  # 缩写
            "title": "法国足球甲级联赛",  # 中文名
            "en_title": "Ligue 1",  # 英文名
            "original_title": "Ligue 1",  # 原名
            "year": 1932,  # 创办年份
            "overview": "法国足球甲级联赛（法语：Championnat de France de football [ʃɑ̃pjɔna də fʁɑ̃s də futbol]，简称Ligue 1 [liɡ œ̃]，因得到赞助商麦当劳冠名而又称为Ligue 1 McDonald's），简称法甲，是法国足球联赛系统的第1级别，亦是职业联赛的最高级别，联赛系统的最高级别和法国顶级足球联赛，由法国足球协会监管下的法国职业足球联赛所负责监督、组织及管理。截至2021年，法甲作为欧洲五大联赛之一，在欧洲足联的联赛系数排名中目前位居全欧第五，仅次于英格兰的英格兰足球超级联赛、西班牙的西班牙足球甲级联赛、意大利的意大利足球甲级联赛和德国的德国足球甲级联赛。\n"
                        "法甲联赛于1932年9月11日成立，最初以“国家联赛”（National）的名称开始运作，一年后改名为“一级联赛”（Division 1）；直到2002年，联赛采用现在的名称。\n"
                        "在 20 世纪时期，法甲联赛较少产生一支长期雄霸联赛的超级强队；即使是法国本土球星，亦是外流至其他欧洲豪门居多；但在九十年代，多支法甲俱乐部在欧洲赛场上冒起，如巴黎圣日耳曼于1996年赢过欧洲杯赛冠军杯，马赛更在1993年赢过欧冠杯。\n"
                        "现在法甲联赛水准已大为提升，并成为了非洲和南美球员向欧洲发展的重要跳板之一。",  # 赛事介绍
            "season_years": {x: x for x in range(1932, 2101)},  # 赛季
            "homepage": "https://www.ligue1.com/",  # 官网
            "languages": ["French"],  # 解说源语言
            "origin_country": "France",  # 国家
            "original_name": "Championnat de France de football",  # 原名
            "production_companies": ["法国足球协会 (FFF)"],  # 创办协会
            "production_countries": ["France"],  # 国家
            "spoken_languages": ["French"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
    ]

def get_demo_competitions_config() -> str:
    desc = (
        "// 以下为自定义赛事配置示例，请参考：https://github.com/Sinterdial/MoviePilot-Plugins/blob/main/docs/Self_Defined_Competitions_Guide.md 进行配置\n"
        "// 插件已内置五大联赛+欧冠+国王杯+西超杯，请勿重复配置\n"
        "// 注意无关内容需使用 // 注释，但行内不要使用 // 注释\n"
        "// 只有标注【必填】的字段是必须有的，其它可以省略\n"
        "// 必须严格遵循 json 格式，最后一个字段后面不要有逗号\n")
    config = """[{
    // 示例一：在 football-data.org 有数据的联赛或杯赛（在线刮削）
    // // 【必填】别名（区分大小写）
    // "names": ["西甲", "La Liga", "LaLiga", "Laliga","西班牙足球甲级联赛"], 
    // // 【必填】赛事类型（联赛：LEAGUE/杯赛：CUP）
    // "type": "LEAGUE", 
    // // 【在线刮削必填】唯一缩写 (需要与 football-data.org 上的缩写对应)，
    // //              该项不要与插件内已有的重复（PD、CL、CDR、SE、PL、SA、BL1、FL1）
    // "shortname": "PD",
    // // 【必填】中文名
    // "title": "西班牙足球甲级联赛",
    // // 英文名
    // "en_title": "La Liga", 
    // // 原名
    // "original_title": "La Liga",  
    // // 创办年份
    // "year": 1929, 
    // // 赛事简介
    // "overview": "赛事简介",
    // // 官网
    // "homepage": "www.laliga.com", 
    // // 解说源语言
    // "languages": ["Spanish"], 
    // // 国家
    // "origin_country": "Spain",  
    // // 原名
    // "original_name": "Primera División de España", 
    // // 创办协会
    // "production_companies": ["西班牙皇家足球协会 (RFEF)"],  
    // // 国家
    // "production_countries": ["Spain"], 
    // // 语言
    // "spoken_languages": ["Spanish"],  
    // // 比赛时长
    // "runtime": 9000,
    // // 【离线刮削必填】本地刮削信息（空表示 football-data.org 上提供该赛事信息，不进行本地刮削)
    // "offline_info": {}
}, 
{
    // // 示例二：football-data.org 没有数据的杯赛（离线刮削）
    // // 【必填】别名（区分大小写）
    // "names": ["西班牙国王杯", "Copa Del Rey", "Campeonato de España – Copa de Su Majestad el Rey", "国王杯"], 
    // // 【必填】赛事类型（联赛：LEAGUE/杯赛：CUP）
    // "type": "CUP", 
    // // 缩写
    // "shortname": "CDR",
    // // 【必填】中文名
    // "title": "西班牙国王杯",
    // // 英文名
    // "en_title": "Copa Del Rey", 
    // // 原名
    // "original_title": "Copa Del Rey",  
    // // 创办年份
    // "year": 1903, 
    // // 赛事简介
    // "overview": "赛事简介",
    // // 官网
    // "homepage": "www.laliga.com/en-GB/other-competitions/copa-del-rey", 
    // // 解说源语言
    // "languages": ["Spanish"], 
    // // 国家
    // "origin_country": "Spain",  
    // // 原名
    // "original_name": "Primera División de España", 
    // // 创办协会
    // "production_companies": ["西班牙皇家足球协会 (RFEF)"],  
    // // 国家
    // "production_countries": ["Spain"], 
    // // 语言
    // "spoken_languages": ["Spanish"],  
    // // 比赛时长
    // "runtime": 9000,
    // // 【必填】
    // "offline_info": {
            // // 【必填】 小组赛比赛场次
            // "group": 0,  
            // // 【必填】 单场淘汰赛起始轮次（例如 32 表示从 32 进 16 这一轮开始），0 表示没有
            // "knockout_single": 32,
            // // 【必填】 主客场淘汰赛起始轮次（例如 32 表示从 32 进 16 这一轮开始），0 表示没有
            // "knockout_double": 4
    // }
}]"""

    return desc + config
