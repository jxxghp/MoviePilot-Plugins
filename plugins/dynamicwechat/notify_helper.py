import re
import requests
from app.modules.wechat import WeChat
from app.schemas.types import NotificationType


class MySender:
    def __init__(self, token=None, func=None):
        self.token = token
        self.channel = self.send_channel() if token else None  # 初始化时确定发送渠道
        self.first_text_sent = False  # 记录是否已发送过纯文本消息
        self.init_success = bool(token)  # 标识初始化成功
        self.post_message_func = func  # V2微信模式的 post_message 方法

    def send_channel(self):
        if "WeChat" in self.token:
            return "WeChat"

        letters_only = ''.join(re.findall(r'[A-Za-z]', self.token))
        if self.token.lower().startswith("sct".lower()):
            return "ServerChan"
        elif letters_only.isupper():
            return "AnPush"
        else:
            return "PushPlus"

    # 标题，内容，图片，是否强制发送
    def send(self, title, content=None, image=None, force_send=False, diy_channel=None):
        if not self.init_success:
            return  # 如果初始化失败，直接返回

        if not image and not force_send:
            if self.first_text_sent:
                return
            else:
                self.first_text_sent = True

        # # 如果是 V2 微信通知直接处理
        if self.channel == "WeChat" and self.post_message_func:
            return self.send_v2_wechat(title, content, image)

        try:
            if not diy_channel:
                channel = self.channel
            else:
                channel = diy_channel

            if channel == "WeChat":
                return MySender.send_wechat(title, content, image, self.token)
            elif channel == "ServerChan":
                return self.send_serverchan(title, content, image)
            elif channel == "AnPush":
                return self.send_anpush(title, content, image)
            elif channel == "PushPlus":
                return self.send_pushplus(title, content, image)
            else:
                return "Unknown channel"
        except Exception as e:
            return f"Error occurred: {str(e)}"

    @staticmethod
    def send_wechat(title, content, image, token):
        wechat = WeChat()
        if ',' in token:
            channel, actual_userid = token.split(',', 1)
        else:
            actual_userid = None
        if image:
            send_status = wechat.send_msg(title='企业微信登录二维码', image=image, link=image, userid=actual_userid)
        else:
            send_status = wechat.send_msg(title=title, text=content)

        if send_status is None:
            return "微信通知发送错误"
        return None

    def send_serverchan(self, title, content, image):
        if self.token.startswith('sctp'):
            match = re.match(r'sctp(\d+)t', self.token)
            if match:
                num = match.group(1)
                url = f'https://{num}.push.ft07.com/send/{self.token}.send'
            else:
                raise ValueError('Invalid sendkey format for sctp')
        else:
            url = f'https://sctapi.ftqq.com/{self.token}.send'

        params = {'title': title, 'desp': f'![img]({image})' if image else content}
        headers = {'Content-Type': 'application/json;charset=utf-8'}
        response = requests.post(url, json=params, headers=headers)
        result = response.json()
        if result.get('code') != 0:
            return f"Server酱通知错误: {result.get('message')}"
        return None

    def send_anpush(self, title, content, image):
        if ',' in self.token:
            channel, token = self.token.split(',', 1)
        else:
            return
        url = f"https://api.anpush.com/push/{token}"
        payload = {
            "title": title,
            "content": f"<img src=\"{image}\" width=\"100%\">" if image else content,
            "channel": channel
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, headers=headers, data=payload)
        result = response.json()
        # 判断返回的code和msgIds
        if result.get('code') != 200:
            return f"AnPush: {result.get('msg')}"
        elif not result.get('data') or not result['data'].get('msgIds'):
            return "AnPush 消息通道未找到"
        return None

    def send_pushplus(self, title, content, image):
        pushplus_url = f"http://www.pushplus.plus/send/{self.token}"
        # PushPlus发送逻辑
        data = {
            "title": title,
            "content": f"企业微信登录二维码<br/><img src='{image}' />" if image else content,
            "template": "html"
        }
        response = requests.post(pushplus_url, json=data)
        result = response.json()
        if result.get('code') != 200:
            return f"PushPlus send failed: {result.get('msg')}"
        return None

    def send_v2_wechat(self, title, content, image):
        """V2 微信通知发送"""
        if not self.token or ',' not in self.token:
            return '没有指定V2微信用户ID'
        channel, actual_userid = self.token.split(',', 1)
        self.post_message_func(
            mtype=NotificationType.Plugin,
            title=title,
            text=content,
            image=image,
            link=image,
            userid=actual_userid
        )
        return None

    def reset_limit(self):
        """解除限制，允许再次发送纯文本消息"""
        self.first_text_sent = False
