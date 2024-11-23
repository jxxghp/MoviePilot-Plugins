import re
import requests
from app.modules.wechat import WeChat
from app.schemas.types import NotificationType,MessageChannel


class MySender:
    def __init__(self, token=None, func=None):
        self.tokens = token.split('||') if token and '||' in token else [token] if token else []
        self.channels = [MySender._detect_channel(t) for t in self.tokens]
        self.current_index = 0  # 当前使用的 token 和 channel 的索引
        self.first_text_sent = False  # 是否已发送过纯文本消息
        self.init_success = bool(self.tokens)  # 标识初始化是否成功
        self.post_message_func = func  # V2 微信模式的 post_message 方法

    @staticmethod
    def _detect_channel(token):
        """根据 token 确定通知渠道"""
        if "WeChat" in token:
            return "WeChat"

        letters_only = ''.join(re.findall(r'[A-Za-z]', token))
        if token.lower().startswith("sct"):
            return "ServerChan"
        elif letters_only.isupper():
            return "AnPush"
        else:
            return "PushPlus"

    def send(self, title, content=None, image=None, force_send=False, diy_channel=None):
        """发送消息"""
        if not self.init_success:
            return

        # 对纯文本消息进行限制
        if not image and not force_send:
            if self.first_text_sent:
                return
            self.first_text_sent = True

        # 如果指定了自定义通道，直接尝试发送
        if diy_channel:
            return self._try_send(title, content, image, diy_channel)

        # 尝试按顺序发送，直到成功或遍历所有通道
        for i in range(len(self.tokens)):
            token = self.tokens[self.current_index]
            channel = self.channels[self.current_index]
            try:
                result = self._try_send(title, content, image, channel, token)
                if result is None:  # 成功时返回 None
                    return
            except Exception as e:
                # 打印错误日志或处理错误
                return f"{channel} 通知错误: {e}"
            # 切换到下一个通道
            self.current_index = (self.current_index + 1) % len(self.tokens)
        return f"所有的通知方式都发送失败"

    def _try_send(self, title, content, image, channel, token=None):
        """尝试使用指定通道发送消息"""
        if channel == "WeChat" and self.post_message_func:
            return self._send_v2_wechat(title, content, image, token)
        elif channel == "WeChat":
            return self._send_wechat(title, content, image, token)
        elif channel == "ServerChan":
            return self._send_serverchan(title, content, image)
        elif channel == "AnPush":
            return self._send_anpush(title, content, image)
        elif channel == "PushPlus":
            return self._send_pushplus(title, content, image)
        else:
            raise ValueError(f"Unknown channel: {channel}")

    @staticmethod
    def _send_wechat(title, content, image, token):
        wechat = WeChat()
        if token and ',' in token:
            channel, actual_userid = token.split(',', 1)
        else:
            actual_userid = None
        if image:
            send_status = wechat.send_msg(title='企业微信登录二维码', image=image, link=image, userid=actual_userid)
        else:
            send_status = wechat.send_msg(title=title, text=content, userid=actual_userid)

        if send_status is None:
            return "微信通知发送错误"
        return None

    def _send_serverchan(self, title, content, image):
        tmp_tokens = self.tokens[self.current_index]
        token = tmp_tokens
        if ',' in tmp_tokens:
            before_comma, after_comma = tmp_tokens.split(',', 1)
            if before_comma.startswith('sctp') and image:
                token = after_comma  # 图片发到公众号
            else:
                token = before_comma  # 发到 server3

        if token.startswith('sctp'):
            match = re.match(r'sctp(\d+)t', token)
            if match:
                num = match.group(1)
                url = f'https://{num}.push.ft07.com/send/{token}.send'
            else:
                return '错误的Server3 Sendkey'
        else:
            url = f'https://sctapi.ftqq.com/{token}.send'

        params = {'title': title, 'desp': f'![img]({image})' if image else content}
        headers = {'Content-Type': 'application/json;charset=utf-8'}
        response = requests.post(url, json=params, headers=headers)
        result = response.json()
        if result.get('code') != 0:
            return f"Server酱通知错误: {result.get('message')}"
        return None

    def _send_anpush(self, title, content, image):
        token = self.tokens[self.current_index]  # 获取当前通道对应的 token
        if ',' in token:
            channel, token = token.split(',', 1)
        else:
            return "可能AnPush 没有配置消息通道ID"
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

    def _send_pushplus(self, title, content, image):
        token = self.tokens[self.current_index]  # 获取当前通道对应的 token
        pushplus_url = f"http://www.pushplus.plus/send/{token}"
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

    def _send_v2_wechat(self, title, content, image, token):
        """V2 微信通知发送"""
        if token and ',' in token:
            channel, actual_userid = token.split(',', 1)
        else:
            actual_userid = None
        self.post_message_func(
            channel=MessageChannel.Wechat,
            mtype=NotificationType.Plugin,
            title=title,
            text=content,
            image=image,
            link=image,
            userid=actual_userid
        )
        return None  # 由于self.post_message()了None外，没有其他返回值。无法判断是否发送成功，V2直接默认成功

    def reset_limit(self):
        """解除限制，允许再次发送纯文本消息"""
        self.first_text_sent = False
