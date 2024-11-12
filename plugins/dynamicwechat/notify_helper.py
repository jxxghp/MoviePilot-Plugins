import re
import requests
from app.modules.wechat.wechat import WeChat


class MySender:
    def __init__(self, token=None):
        if not token:  # 如果 token 为空
            self.token = None
            self.channel = None
            self.init_success = False  # 标识初始化失败
        else:
            self.token = token
            self.channel = self.send_channel()  # 初始化时确定发送渠道
            self.first_text_sent = False  # 记录是否已经发送过纯文本消息
            self.init_success = True  # 标识初始化成功

    def send_channel(self):
        if self.token:
            if self.token == "WeChat":
                return "WeChat"

            letters_only = ''.join(re.findall(r'[A-Za-z]', self.token))
            # 判断其他推送渠道
            if self.token.startswith("SCT"):
                return "ServerChan"
            elif letters_only.isupper():
                return "AnPush"
            else:
                return "PushPlus"
        return None

    # 标题，内容，图片，是否强制发送
    def send(self, title, content, image=None, force_send=False, diy_channel=None):
        if not self.init_success:
            return  # 如果初始化失败，直接返回
        # 判断发送的内容类型
        contains_image = bool(image)  # 是否包含图片

        if not contains_image and not force_send:
            if self.first_text_sent:
                return
            else:
                self.first_text_sent = True

        try:
            if not diy_channel:
                channel = self.channel
            else:
                channel = diy_channel

            if channel == "WeChat":
                return MySender.send_wechat(title, content, image)
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
    def send_wechat(title, content, image):
        wechat = WeChat()
        if image:
            send_status = wechat.send_msg(title='企业微信登录二维码', image=image, link=image)
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

    def reset_limit(self):
        """解除限制，允许再次发送纯文本消息"""
        self.first_text_sent = False
