import json
import time
from typing import List, Union

import openai
from cacheout import Cache

OpenAISessionCache = Cache(maxsize=100, ttl=3600, timer=time.time, default=None)


class OpenAi:
    _api_key: str = None
    _api_url: str = None
    _model: str = "gpt-3.5-turbo"

    def __init__(self, api_key: str = None, api_url: str = None, proxy: dict = None, model: str = None, compatible: bool = False):
        self._api_key = api_key
        self._api_url = api_url
        if compatible:
            openai.api_base = self._api_url
        else:
            openai.api_base = self._api_url + "/v1"
        openai.api_key = self._api_key
        if proxy and proxy.get("https"):
            openai.proxy = proxy.get("https")
        if model:
            self._model = model

    def get_state(self) -> bool:
        return True if self._api_key else False

    @staticmethod
    def __save_session(session_id: str, message: str):
        """
        세션 저장
        :param session_id: 세션 ID
        :param message: 메시지
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
        세션 가져오기
        :param session_id: 세션 ID
        :return: 대화 컨텍스트
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
        모델 호출
        """
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
        return openai.ChatCompletion.create(
            model=self._model,
            user=user,
            messages=message,
            **kwargs
        )

    @staticmethod
    def __clear_session(session_id: str):
        """
        세션 삭제
        :param session_id: 세션 ID
        :return:
        """
        if OpenAISessionCache.get(session_id):
            OpenAISessionCache.delete(session_id)

    def get_media_name(self, filename: str):
        """
        파일명에서 미디어 제목 등의 요소 추출
        :param filename: 파일명
        :return: JSON
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _filename_prompt = "I will give you a movie/tvshow file name.You need to return a Json." \
                               "\nPay attention to the correct identification of the film name." \
                               "\n{\"title\":string,\"version\":string,\"part\":string,\"year\":string,\"resolution\":string,\"season\":number|null,\"episode\":number|null}"
            completion = self.__get_model(prompt=_filename_prompt, message=filename)
            result = completion.choices[0].message.content
            return json.loads(result)
        except Exception as e:
            print(f"{str(e)}：{result}")
            return {}

    def get_response(self, text: str, userid: str):
        """
        채팅 대화, 응답 얻기
        :param text: 입력 텍스트
        :param userid: 사용자 ID
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
            # 이전 대화 컨텍스트 가져오기
            messages = self.__get_session(userid, text)
            completion = self.__get_model(message=messages, user=userid)
            result = completion.choices[0].message.content
            if result:
                self.__save_session(userid, text)
            return result
        except openai.error.RateLimitError as e:
            return f"요청이 ChatGPT에 의해 거부되었습니다：{str(e)}"
        except openai.error.APIConnectionError as e:
            return f"ChatGPT 네트워크 연결 실패：{str(e)}"
        except openai.error.Timeout as e:
            return f"ChatGPT로부터 응답이 없습니다：{str(e)}"
        except Exception as e:
            return f"ChatGPT 요청 중 오류 발생：{str(e)}"

    def translate_to_zh(self, text: str):
        """
        중국어로 번역
        :param text: 입력 텍스트
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
        주어진 문제와 선택지에서 정답 찾기
        :param question: 문제 및 선택지
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
