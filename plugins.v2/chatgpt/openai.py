import json
import re
import time
from typing import List, Union

import openai
from cacheout import Cache

OpenAISessionCache = Cache(maxsize=100, ttl=3600, timer=time.time, default=None)


class OpenAi:
    _api_key: str = None
    _api_url: str = None
    _model: str = "gpt-3.5-turbo"
    _prompt: str = '接下来我会给你一个电影或电视剧的文件名，你需要识别文件名中的名称、版本、分段、年份、分瓣率、季集等信息，并按以下JSON格式返回：{"name":string,"version":string,"part":string,"year":string,"resolution":string,"season":number|null,"episode":number|null}，特别注意返回结果需要严格附合JSON格式，不需要有任何其它的字符。如果中文电影或电视剧的文件名中存在谐音字或字母替代的情况，请还原最有可能的结果。'
    _client: openai.OpenAI = None

    def __init__(self, api_key: str = None, api_url: str = None,
                 proxy: dict = None, model: str = None,
                 compatible: bool = False, customize_prompt: str = None):
        self._api_key = api_key
        self._api_url = api_url
        if model:
            self._model = model
        if customize_prompt:
            self._prompt = customize_prompt
        
        # 初始化 OpenAI 客户端
        if self._api_key and self._api_url:
            base_url = self._api_url if compatible else self._api_url + "/v1"
            http_client = None
            if proxy and proxy.get("https"):
                import httpx
                proxy_url = proxy.get("https")
                # httpx 支持字符串格式的代理 URL
                http_client = httpx.Client(proxies=proxy_url, timeout=60.0)
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=base_url,
                http_client=http_client
            )

    def get_state(self) -> bool:
        return True if self._api_key else False

    @staticmethod
    def __save_session(session_id: str, message: str):
        """
        保存会话
        :param session_id: 会话ID
        :param message: 消息
        :return:
        """
        seasion = OpenAISessionCache.get(session_id)
        if seasion:
            seasion.append({
                "role": "assistant",
                "content": message
            })
            OpenAISessionCache.set(session_id, seasion)

    @staticmethod
    def __get_session(session_id: str, message: str) -> List[dict]:
        """
        获取会话
        :param session_id: 会话ID
        :return: 会话上下文
        """
        seasion = OpenAISessionCache.get(session_id)
        if seasion:
            seasion.append({
                "role": "user",
                "content": message
            })
        else:
            seasion = [
                {
                    "role": "system",
                    "content": "请在接下来的对话中请使用中文回复，并且内容尽可能详细。"
                },
                {
                    "role": "user",
                    "content": message
                }]
            OpenAISessionCache.set(session_id, seasion)
        return seasion

    def __get_model(self, message: Union[str, List[dict]],
                    prompt: str = None,
                    user: str = "MoviePilot",
                    **kwargs):
        """
        获取模型
        """
        if not self._client:
            raise ValueError("OpenAI client not initialized. Please check API key and API URL.")
        if not isinstance(message, list):
            if prompt:
                message = [
                    {
                        "role": "system",
                        "content": prompt
                    },
                    {
                        "role": "user",
                        "content": message
                    }
                ]
            else:
                message = [
                    {
                        "role": "user",
                        "content": message
                    }
                ]
        # 新版本 API 不支持 user 参数，需要从 kwargs 中移除
        kwargs.pop('user', None)
        return self._client.chat.completions.create(
            model=self._model,
            messages=message,
            **kwargs
        )

    @staticmethod
    def __clear_session(session_id: str):
        """
        清除会话
        :param session_id: 会话ID
        :return:
        """
        if OpenAISessionCache.get(session_id):
            OpenAISessionCache.delete(session_id)

    def get_media_name(self, filename: str):
        """
        从文件名中提取媒体名称等要素
        :param filename: 文件名
        :return: Json
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _filename_prompt = self._prompt
            completion = self.__get_model(prompt=_filename_prompt, message=filename)
            result = completion.choices[0].message.content
            # 有些模型返回json数据时会使用 ```json ``` 包裹json对象 所以需要进行提取
            # 定义正则表达式模式，匹配```json开头和```结尾的内容
            pattern = r'^```json\s*([\s\S]*?)\s*```$'
            # 使用正则表达式进行匹配
            match = re.match(pattern, result.strip())
            if match:
                # 提取中间的JSON部分
                result = match.group(1)
            return json.loads(result)
        except Exception as e:
            return {
                "content": result,
                "errorMsg": str(e)
            }

    def get_response(self, text: str, userid: str):
        """
        聊天对话，获取答案
        :param text: 输入文本
        :param userid: 用户ID
        :return:
        """
        if not self.get_state():
            return ""
        try:
            if not userid:
                return "用户信息错误"
            else:
                userid = str(userid)
            if text == "#清除":
                self.__clear_session(userid)
                return "会话已清除"
            # 获取历史上下文
            messages = self.__get_session(userid, text)
            completion = self.__get_model(message=messages, user=userid)
            result = completion.choices[0].message.content
            if result:
                self.__save_session(userid, text)
            return result
        except openai.RateLimitError as e:
            return f"请求被ChatGPT拒绝了，{str(e)}"
        except openai.APIConnectionError as e:
            return f"ChatGPT网络连接失败：{str(e)}"
        except openai.APITimeoutError as e:
            return f"没有接收到ChatGPT的返回消息：{str(e)}"
        except Exception as e:
            return f"请求ChatGPT出现错误：{str(e)}"

    def translate_to_zh(self, text: str):
        """
        翻译为中文
        :param text: 输入文本
        """
        if not self.get_state():
            return False, None
        system_prompt = "You are a translation engine that can only translate text and cannot interpret it."
        user_prompt = f"translate to zh-CN:\n\n{text}"
        result = ""
        try:
            completion = self.__get_model(prompt=system_prompt,
                                          message=user_prompt,
                                          temperature=0,
                                          top_p=1,
                                          frequency_penalty=0,
                                          presence_penalty=0)
            result = completion.choices[0].message.content.strip()
            return True, result
        except Exception as e:
            print(f"{str(e)}：{result}")
            return False, str(e)

    def get_question_answer(self, question: str):
        """
        从给定问题和选项中获取正确答案
        :param question: 问题及选项
        :return: Json
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _question_prompt = "下面我们来玩一个游戏，你是老师，我是学生，你需要回答我的问题，我会给你一个题目和几个选项，你的回复必须是给定选项中正确答案对应的序号，请直接回复数字"
            completion = self.__get_model(prompt=_question_prompt, message=question)
            result = completion.choices[0].message.content
            return result
        except Exception as e:
            print(f"{str(e)}：{result}")
            return {}
