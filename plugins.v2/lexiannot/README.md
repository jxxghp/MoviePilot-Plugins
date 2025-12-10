# 美剧生词标注

根据CEFR等级，为英语影视剧标注高级词汇。
___
在影视剧入库后，LexiAnnot 会读取媒体文件的MediaInfo和文件列表，如果视频的原始语言为英语并且包含英文文本字幕，LexiAnnot将为其生成包含词汇注释的`.en.ass`字幕文件。

## 主要功能

![](https://images2.imgbox.com/d6/b6/kZu6EH2a_o.png)
![](https://images2.imgbox.com/c8/3a/rEJBWu5v_o.png)
![](https://images2.imgbox.com/56/c0/FBhJMvRD_o.jpg)
![](https://images2.imgbox.com/8a/d4/AtgOe265_o.jpg)

- 识别视频的原始语言和字幕语言
- 自动适应原字幕样式
- 俚语 / 自造词 / 熟词生义标注和解释

## 使用配置

- spaCy 模型
  - spaCy 用于词形还原、POS 标注和命名实体识别，`en_core_web_sm`或`en_core_web_md` 已足够满足需求。
- LLM 设置
  - 一集影视剧的字幕通常包含数千个单词，建议使用支持长文本输入的模型，选择一个适当的上下文窗口大小。
  - 处理 60 min 的影视剧字幕大约会消耗 `60K`~`80K` token，具体取决于字幕内容。
  - 配置请参考 MoviePilot 智能助手的设置部分。
- Agent 工具
  - 在聊天中使用 `/ai` 命令告诉智能助手你要标注的影视剧。

## CEFR

CEFR全称是Common European Framework of Reference for Languages。

它是一个国际标准，用于描述语言学习者的语言能力水平。CEFR 将语言能力分为六个级别，并进一步归类为三大使用者类型：

- **A - 基础使用者 (Basic User)**
  - **A1** (初学者/Beginner)：能够理解并使用日常熟悉的表达和非常基本的短语。
  - **A2** (初级/Elementary)：能够理解基本的表达方式，并以简单的方式进行交流。
- **B - 独立使用者 (Independent User)**
  - **B1** (中级/Intermediate)：能够理解熟悉主题的主要观点，可以处理旅行中可能遇到的多数情况，并能就熟悉的话题发表意见和描述。
  - **B2** (中高级/Upper-Intermediate)：能够理解复杂文本的主要思想，并能与母语者进行一定程度的流利、自然的互动，可以就广泛的主题进行清晰、详细的阐述。
- **C - 熟练使用者 (Proficient User)**
  - **C1** (高级/Advanced)：能够理解各种较长、要求较高的文本，并能识别隐含意义，表达流利、自然，能灵活有效地使用语言来应对各种目的。
  - **C2** (精通/Proficient)：能够轻松理解几乎所有听到的或读到的内容，能够非常流利、准确、精细地表达自己，即使在复杂的情况下也能区分细微的含义。

## 计划

- 双语字幕支持
- ~~考试词汇标注~~

## FAQ

- **只能处理已有字幕的视频吗？**
  - 是的，视频需要包含**英文文本字幕**
- **为什么无法处理一些包含字幕视频**
  - 目前无法识别基于图片的字幕(通常是特效字幕)

## 感谢

- [coca-vocabulary-20000](https://github.com/llt22/coca-vocabulary-20000)