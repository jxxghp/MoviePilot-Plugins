import json
import os # Not strictly used in this snippet, but often present
import time
from io import BytesIO
from typing import Tuple
from pathlib import Path # 导入 Path
import requests # 导入 requests (用于 URL 编码和 RequestUtils mock)
import random # For random sleep

from PIL import Image
from lxml import etree
from ruamel.yaml import CommentedMap # 如果你项目中确实用到，否则可以移除

# 假设这些是你项目中的模块
# 如果是独立运行，确保 settings, logger, _ISiteSigninHandler, StringUtils 有 Mock 实现
# --- Minimal Mock Objects for Standalone Testing if app.* modules are not available ---
# (Ensure these are defined if you are running this script standalone for testing)
if 'settings' not in globals():
    class MockSettings:
        def __init__(self):
            self.TEMP_PATH = Path("./temp_data") # Ensure TEMP_PATH returns a Path object
            self.PROXY = None 
    settings = MockSettings()
    if not settings.TEMP_PATH.exists(): settings.TEMP_PATH.mkdir(parents=True, exist_ok=True)

if 'logger' not in globals():
    import logging
    # Basic logger setup
    logger = logging.getLogger(__name__) # Use a unique name for the logger
    logger.setLevel(logging.INFO) # Changed to INFO for better visibility during testing
    # Prevent duplicate handlers if this script is run multiple times in the same session
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('【%(levelname)s】%(asctime)s - %(filename)s:%(lineno)d - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False # Prevent logging from propagating to the root logger

if '_ISiteSigninHandler' not in globals():
    class _ISiteSigninHandler: pass # Minimal stub

if 'StringUtils' not in globals():
    class StringUtils:
        @staticmethod
        def url_equal(url1, url2):
            u1 = url1.strip().lower().replace("https://", "").replace("http://", "").rstrip('/')
            u2 = url2.strip().lower().replace("https://", "").replace("http://", "").rstrip('/')
            return u1 == u2
# --- End Mock Objects ---

# from app.core.config import settings # Using Mock if not available
# from app.log import logger # Using Mock if not available
# from app.plugins.autosignin.sites import _ISiteSigninHandler # Using Mock if not available
# from app.utils.string import StringUtils # Using Mock if not available


# --- RequestUtils 定义或 Mock ---
class CustomRequestUtils:
    def __init__(self, cookies=None, ua=None, proxies=None, referer=None):
        self.session = requests.Session()
        
        browser_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36" 
        )
        
        self.session.headers['User-Agent'] = ua if ua else browser_ua
        self.session.headers['Accept'] = 'application/json, text/plain, */*'
        self.session.headers['Accept-Language'] = 'zh-CN,zh;q=0.9,en;q=0.8'

        if cookies:
            cookie_dict = {}
            if isinstance(cookies, str):
                for item in cookies.split(';'):
                    parts = item.split('=', 1)
                    if len(parts) == 2:
                        cookie_dict[parts[0].strip()] = parts[1].strip()
            elif isinstance(cookies, dict):
                cookie_dict = cookies
            self.session.cookies.update(cookie_dict)
        
        if referer: 
            self.session.headers['Referer'] = referer
        
        if proxies: 
            self.session.proxies = proxies

    def get_res(self, url, timeout=20):
        # logger.info(f"RequestUtils: 发起 GET 请求到 {url}")
        try: 
            response = self.session.get(url, timeout=timeout)
            return response 
        except requests.RequestException as e: 
            logger.error(f"RequestUtils: GET 请求 {url} 失败: {e}")
            return None

    def post_res(self, url, data=None, timeout=20):
        # logger.info(f"RequestUtils: 发起 POST 请求到 {url}")
        try: 
            response = self.session.post(url, data=data, timeout=timeout)
            return response
        except requests.RequestException as e: 
            logger.error(f"RequestUtils: POST 请求 {url} 失败: {e}")
            return None

RequestUtils = CustomRequestUtils
# --- End RequestUtils ---


class Tjupt(_ISiteSigninHandler):
    """
    北洋签到
    """
    site_url = "tjupt.org"
    _sign_in_url = 'https://www.tjupt.org/attendance.php'
    _sign_regex = ['<a href="attendance.php">今日已签到</a>']
    _succeed_regex = [
        '这是您的首次签到，本次签到获得\\d+个魔力值。',
        '签到成功，这是您的第\\d+次签到，已连续签到\\d+天，本次签到获得\\d+个魔力值。',
        '重新签到成功，本次签到获得\\d+个魔力值',
        '签到成功'
    ]
    _answer_path = Path(settings.TEMP_PATH) / "signin/"
    _answer_file = _answer_path / "tjupt.json"
    _info_img_path = _answer_path / "tjupt_info_images/"


    @classmethod
    def match(cls, url: str) -> bool:
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        site = site_info.get("name", "Tjupt") # Default site name
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua") 
        proxy = site_info.get("proxy")
        render = site_info.get("render") # render is not used in current get_page_source

        if not self._answer_path.exists():
            self._answer_path.mkdir(parents=True, exist_ok=True)
        if not self._info_img_path.exists():
            self._info_img_path.mkdir(parents=True, exist_ok=True)

        html_text = self.get_page_source(
            url=self._sign_in_url, cookie=site_cookie, ua=ua, proxy=proxy, render=render
        )

        if not html_text:
            logger.error(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'
        if "login.php" in html_text:
            logger.error(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        sign_status_msg = self.sign_in_result(html_res=html_text, regexs=self._sign_regex)
        if sign_status_msg:
            logger.info(f"{site} 今日已签到: {sign_status_msg}")
            return True, sign_status_msg

        html = etree.HTML(html_text)
        if html is None:
            logger.error(f"{site} 签到失败，无法解析HTML")
            return False, '签到失败，无法解析HTML'
        
        img_elements = html.xpath('//table[@class="captcha"]//img/@src')
        if not img_elements:
            logger.error(f"{site} 签到失败，未获取到签到图片路径")
            return False, '签到失败，未获取到签到图片路径'
        img_url_path = img_elements[0]

        if not img_url_path.startswith("http"):
            img_url = "https://www.tjupt.org" + (img_url_path if img_url_path.startswith('/') else '/' + img_url_path)
        else:
            img_url = img_url_path
        logger.info(f"获取到签到图片URL: {img_url}")
        
        captcha_img_res = RequestUtils(cookies=site_cookie, ua=ua, proxies=settings.PROXY if proxy else None).get_res(url=img_url)
        if not captcha_img_res or captcha_img_res.status_code != 200:
            logger.error(f"{site} 签到图片 {img_url} 请求失败 (Status: {captcha_img_res.status_code if captcha_img_res else 'N/A'})")
            return False, '签到失败，未获取到签到图片'
        
        try:
            captcha_img = Image.open(BytesIO(captcha_img_res.content))
        except Exception as e:
            logger.error(f"{site} 签到图片 {img_url} 打开失败: {e}")
            return False, '签到失败，签到图片处理错误'
            
        captcha_img_hash = self._tohash(captcha_img)
        logger.info(f"签到图片hash: {captcha_img_hash}") 
        
        captcha_filename = f"captcha_{captcha_img_hash}.png"
        try:
            captcha_img.save(self._info_img_path / captcha_filename)
            logger.info(f"已保存签到图片用于调试: {self._info_img_path / captcha_filename}")
        except Exception as e:
            logger.error(f"保存签到图片失败: {e}")

        values = html.xpath("//input[@name='ban_robot']/@value")
        labels = html.xpath("//label[input/@name='ban_robot']")
        options_raw_text = []
        for label_idx, label in enumerate(labels):
            current_label_texts = label.xpath("./text()")
            processed_text_for_label = ""
            for text_node in current_label_texts:
                cleaned_text = text_node.strip()
                if cleaned_text:
                    processed_text_for_label = cleaned_text.strip('"')
                    break 
            if not processed_text_for_label: # Fallback if no direct text(), might be inside a span or other element
                child_texts = label.xpath(".//*[self::span or self::font]/text()") # Example, adjust if needed
                for child_text_node in child_texts:
                    cleaned_child_text = child_text_node.strip()
                    if cleaned_child_text:
                        processed_text_for_label = cleaned_child_text.strip('"')
                        break
            if not processed_text_for_label:
                logger.warning(f"标签 {label_idx+1} 未直接找到文本内容，HTML结构可能已改变或XPath需调整。label HTML: {etree.tostring(label, encoding='unicode')[:100]}")
            options_raw_text.append(processed_text_for_label)
        
        options = options_raw_text

        if not values or not options or not any(opt for opt in options if opt.strip()): # Check for non-empty options
            logger.error(f"{site} 签到失败，未获取到有效答案选项. Values: {values}, Options: {options}")
            return False, '签到失败，未获取到有效答案选项'
        if len(values) != len(options):
            logger.error(f"{site} 签到失败，答案选项和值数量不匹配. Values ({len(values)}): {values}, Options ({len(options)}): {options}")
            return False, '签到失败，答案选项和值数量不匹配'

        answers = list(zip(values, options))
        logger.info(f"获取到所有签到选项: {answers}")

        exits_answers = {}
        if self._answer_file.exists():
            try:
                with open(self._answer_file, 'r', encoding='utf-8') as f:
                    json_str = f.read()
                if json_str:
                    exits_answers = json.loads(json_str)
                captcha_answer_text_from_cache = exits_answers.get(captcha_img_hash) # Renamed variable
                if captcha_answer_text_from_cache:
                    logger.info(f"本地缓存找到hash {captcha_img_hash} -> 答案文本: '{captcha_answer_text_from_cache}'")
                    for value, option_text in answers:
                        if str(captcha_answer_text_from_cache) == str(option_text):
                            logger.info(f"使用本地缓存答案: '{option_text}' (对应表单值为: {value})")
                            return self.__signin(answer_value_to_submit=value,
                                                 answer_text_for_storage=option_text,
                                                 site_cookie=site_cookie, ua=ua, proxy=proxy, site=site,
                                                 is_from_local_cache=True)
            except FileNotFoundError:
                logger.info(f"本地答案文件 {self._answer_file} 未找到，将尝试豆瓣查询。")
            except (IOError, OSError, json.JSONDecodeError) as e:
                logger.error(f"读取或解析本地答案文件失败: {str(e)}，将尝试豆瓣查询。")
        else:
            logger.info(f"本地答案文件 {self._answer_file} 不存在，将尝试豆瓣查询。")
        
        # --- MODIFICATION FOR HIGHEST SIMILARITY ---
        highest_overall_similarity_score = -1.0 
        selected_answer_payload = None # Will store (value_to_submit, answer_text_option)
        
        # Minimum acceptable similarity. If the best match is below this, it's not considered a valid match.
        # This can be adjusted based on how reliable the image hashing is.
        MIN_ACCEPTABLE_SIMILARITY = site_info.get("min_similarity_threshold", 0.60) # Allow override from site_info

        for option_idx, (current_value_to_submit, current_answer_text_option) in enumerate(answers):
            if not current_answer_text_option or not current_answer_text_option.strip():
                logger.info(f"TJUPT选项 {option_idx+1} 文本为空或仅含空格 ('{current_answer_text_option}'), 跳过豆瓣查询。")
                continue

            logger.info(f"开始评估TJUPT选项 {option_idx+1}/{len(answers)}: '{current_answer_text_option}' (表单值: {current_value_to_submit})")
            
            # Use requests.utils.quote for proper URL encoding of query parameters
            search_query = requests.utils.quote(current_answer_text_option)
            douban_url = f'https://movie.douban.com/j/subject_suggest?q={search_query}'
            
            db_req_utils = RequestUtils(ua=ua, proxies=settings.PROXY if proxy else None, referer="https://movie.douban.com/")
            db_res = db_req_utils.get_res(url=douban_url)
            
            if not db_res: # Request failed (network error, etc.)
                logger.warning(f"豆瓣API请求失败 (无响应) for '{current_answer_text_option}'. 跳过此选项的豆瓣结果。")
                time.sleep(random.uniform(1.0, 2.0)) # Slightly longer pause on complete failure
                continue
            if db_res.status_code != 200:
                logger.warning(f"豆瓣API请求返回状态码 {db_res.status_code} for '{current_answer_text_option}'. Response: {db_res.text[:100]}. 跳过此选项的豆瓣结果。")
                time.sleep(random.uniform(0.5, 1.5)) 
                continue
            
            try:
                # Ensure response is not empty before attempting JSON decode
                if not db_res.text or not db_res.text.strip():
                    logger.info(f"豆瓣API响应为空 for '{current_answer_text_option}'. 跳过此选项的豆瓣结果。")
                    continue # Go to next TJUPT option
                db_answers_json = db_res.json()
            except requests.exceptions.JSONDecodeError as e:
                logger.error(f"豆瓣响应JSON解析失败 for '{current_answer_text_option}'. Error: {e}. Response text: {db_res.text[:200]}. 跳过此选项的豆瓣结果。")
                time.sleep(random.uniform(0.5, 1.5))
                continue # Go to next TJUPT option
            
            if not isinstance(db_answers_json, list): db_answers_json = [db_answers_json]
            if not db_answers_json: 
                logger.info(f"豆瓣未返回有效搜索结果 for '{current_answer_text_option}'.")
                continue # Go to next TJUPT option

            best_similarity_for_this_tjupt_option = -1.0
            
            for db_entry_idx, db_answer_item in enumerate(db_answers_json):
                douban_img_url = db_answer_item.get('img')
                douban_title = db_answer_item.get('title', 'N/A')

                if not douban_img_url:
                    logger.info(f"  豆瓣条目 '{douban_title}' (for TJUPT option '{current_answer_text_option}') 无图片信息，跳过。")
                    continue
                
                # logger.debug(f"  处理豆瓣条目 {db_entry_idx+1}/{len(db_answers_json)} for '{current_answer_text_option}': '{douban_title}' (图片: {douban_img_url})")
                
                douban_img_req_utils = RequestUtils(ua=ua, proxies=settings.PROXY if proxy else None, referer="https://movie.douban.com/") # New instance is fine
                answer_img_res = douban_img_req_utils.get_res(url=douban_img_url)

                if not answer_img_res or answer_img_res.status_code != 200:
                    logger.error(f"  下载豆瓣图片失败: '{douban_title}' from {douban_img_url}. Status: {answer_img_res.status_code if answer_img_res else 'N/A'}")
                    continue # Try next Douban item
                
                try:
                    douban_img_obj = Image.open(BytesIO(answer_img_res.content))
                except Exception as e:
                    logger.error(f"  打开豆瓣图片失败: '{douban_title}' from {douban_img_url}. Error: {e}")
                    continue # Try next Douban item

                douban_img_hash = self._tohash(douban_img_obj)
                
                # Save Douban image for debugging (optional, can be commented out)
                safe_option_text = "".join(c if c.isalnum() else "_" for c in current_answer_text_option)[:30]
                douban_img_filename = f"douban_{safe_option_text}_entry{db_entry_idx}_{douban_img_hash}.png"
                try:
                    if not (self._info_img_path / douban_img_filename).exists(): # Avoid re-saving identical images
                         douban_img_obj.save(self._info_img_path / douban_img_filename)
                         # logger.debug(f"  已保存豆瓣图片: {self._info_img_path / douban_img_filename}")
                except Exception as e:
                    logger.warning(f"  保存豆瓣图片失败: {e}")

                current_comparison_score = self._comparehash(captcha_img_hash, douban_img_hash)
                logger.info(f"  -> 对比 (TJUPT:'{current_answer_text_option}' vs Douban:'{douban_title}'): 相似度 = {current_comparison_score:.4f}")

                if current_comparison_score > best_similarity_for_this_tjupt_option:
                    best_similarity_for_this_tjupt_option = current_comparison_score
                
                # Small delay between individual Douban image downloads/processing for one TJUPT option
                time.sleep(random.uniform(0.2, 0.4)) 

            logger.info(f"对于TJUPT选项 '{current_answer_text_option}', 与其豆瓣搜索结果图片的最高相似度为: {best_similarity_for_this_tjupt_option:.4f}")
            if best_similarity_for_this_tjupt_option > highest_overall_similarity_score:
                highest_overall_similarity_score = best_similarity_for_this_tjupt_option
                selected_answer_payload = (current_value_to_submit, current_answer_text_option)
                logger.info(f"*** 新的全局最高相似度答案候选: '{current_answer_text_option}' (值: {current_value_to_submit}), 相似度: {highest_overall_similarity_score:.4f} ***")
            
            # Delay between processing different TJUPT options, if there are more to process
            if len(answers) > 1 and option_idx < len(answers) - 1:
                 logger.info(f"完成对TJUPT选项 '{current_answer_text_option}' 的评估，暂停1-2秒。")
                 time.sleep(random.uniform(1, 2)) 
        
        # After checking all TJUPT answers against their Douban results
        if selected_answer_payload and highest_overall_similarity_score >= MIN_ACCEPTABLE_SIMILARITY:
            final_value_to_submit, final_answer_text = selected_answer_payload
            logger.info(f"最终选择的答案是 '{final_answer_text}' (表单值: {final_value_to_submit}) "
                        f"基于最高相似度: {highest_overall_similarity_score:.4f} (最低要求: {MIN_ACCEPTABLE_SIMILARITY:.2f})")
            return self.__signin(answer_value_to_submit=final_value_to_submit,
                                 answer_text_for_storage=final_answer_text,
                                 site_cookie=site_cookie, ua=ua, proxy=proxy, site=site,
                                 exits_answers=exits_answers, captcha_img_hash=captcha_img_hash,
                                 is_from_local_cache=False) # Explicitly False as it's from Douban
        else:
            if selected_answer_payload: # A best was found, but it was too low
                 logger.error(f"{site}: 所有选项评估完毕. 最高相似度为 {highest_overall_similarity_score:.4f} "
                              f"(来自选项 '{selected_answer_payload[1]}'), 但未达到最低阈值 {MIN_ACCEPTABLE_SIMILARITY:.2f}。")
            else: # No match at all (e.g., all Douban queries failed, returned no images, or all options were empty)
                 logger.error(f"{site}: 未能从豆瓣结果中计算任何有效的相似度，或所有选项均无法处理。")

            logger.info(f"{site}: 当前验证码图片哈希为: {captcha_img_hash}")
            logger.info(f"{site}: 当前可选答案为: {answers}")
            if answers and captcha_img_hash and answers[0][1]: # Ensure there's something to suggest
                logger.info(f"{site}: 请手动访问签到页面，确认正确答案后，将其添加到 '{self._answer_file}' 文件中。例如，如果正确答案是 '{answers[0][1]}', "
                            f"则在JSON文件中添加条目 '\"{captcha_img_hash}\": \"{answers[0][1]}\"'")
            return False, (f'签到失败，豆瓣查询未找到足够相似的答案 (最高相似度 {highest_overall_similarity_score:.2f}, '
                           f'需要 {MIN_ACCEPTABLE_SIMILARITY:.2f}) 且本地无答案。请检查日志并考虑手动更新答案库: {self._answer_file}')
        # --- END MODIFICATION ---

    def __signin(self, answer_value_to_submit, answer_text_for_storage, site_cookie, ua, proxy, site, 
                 exits_answers=None, captcha_img_hash=None, is_from_local_cache=False):
        data = {
            'ban_robot': answer_value_to_submit,
            'submit': '提交' # Make sure this value is correct for tjupt.org
        }
        logger.info(f"准备提交签到。选择的答案文本: '{answer_text_for_storage}', 提交的表单值: '{answer_value_to_submit}'")
        logger.info(f"提交的签到数据 (POST data): {data}")
        
        sign_in_req_utils = RequestUtils(cookies=site_cookie, ua=ua, proxies=settings.PROXY if proxy else None)
        # Important: The referer for the POST request should be the attendance page itself.
        sign_in_req_utils.session.headers['Referer'] = self._sign_in_url 
        sign_in_res = sign_in_req_utils.post_res(url=self._sign_in_url, data=data)
        
        if not sign_in_res:
             logger.error(f"{site} 签到接口请求失败 (无响应).")
             return False, '签到失败，签到接口请求失败 (无响应)'
        if sign_in_res.status_code != 200: # PT sites might redirect on success (302) or other codes
            # Check for success regex even if status code is not 200, as some sites redirect
            sign_success_message_on_nontypical_status = self.sign_in_result(html_res=sign_in_res.text, regexs=self._succeed_regex)
            if sign_success_message_on_nontypical_status:
                logger.info(f"{site} 签到成功 (状态码 {sign_in_res.status_code})! 消息: {sign_success_message_on_nontypical_status}")
                if exits_answers is not None and captcha_img_hash and not is_from_local_cache:
                    self.__write_local_answer(exits_answers=exits_answers,
                                              captcha_img_hash=captcha_img_hash,
                                              answer_text=answer_text_for_storage)
                return True, sign_success_message_on_nontypical_status
            
            error_text = sign_in_res.text[:200] if hasattr(sign_in_res, 'text') else 'N/A'
            logger.error(f"{site} 签到接口请求失败. Status: {sign_in_res.status_code}. Response: {error_text}")
            return False, f'签到失败，签到接口请求状态码: {sign_in_res.status_code}'

        sign_success_message = self.sign_in_result(html_res=sign_in_res.text, regexs=self._succeed_regex)
        if sign_success_message:
            logger.info(f"{site} 签到成功! 消息: {sign_success_message}")
            if exits_answers is not None and captcha_img_hash and not is_from_local_cache: # ensure exits_answers initialized
                self.__write_local_answer(exits_answers=exits_answers,
                                          captcha_img_hash=captcha_img_hash,
                                          answer_text=answer_text_for_storage)
            return True, sign_success_message
        else:
            error_message = f"{site} 签到失败，请到页面查看。"
            fail_tree = etree.HTML(sign_in_res.text)
            if fail_tree is not None:
                # More generic error message search from common PT site error display
                error_elements = fail_tree.xpath('//td[@class="text" and (contains(string(.), "错误") or contains(string(.), "失败") or contains(string(.), "Error"))]//text() | //p[@class="text" and (contains(string(.), "错误") or contains(string(.), "失败") or contains(string(.), "Error"))]//text()')
                if not error_elements:
                    # Try another common pattern for messages
                    error_elements = fail_tree.xpath('//table[contains(@class, "message") or contains(@id, "message")]//td[@class="text"]//text()')
                extracted_errors = [e.strip() for e in error_elements if e.strip()]
                if extracted_errors: error_message += " 站点返回: " + " ".join(extracted_errors)
                else: logger.info(f"{site} 签到失败响应内容片段 (未匹配到特定错误消息): {sign_in_res.text[:500]}")
            logger.error(error_message)
            return False, error_message

    def __write_local_answer(self, exits_answers, captcha_img_hash, answer_text):
        try:
            # Ensure the path exists right before writing
            if not self._answer_path.exists():
                self._answer_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created answer path: {self._answer_path}")

            exits_answers[str(captcha_img_hash)] = str(answer_text) # Ensure keys and values are strings
            formatted_data = json.dumps(exits_answers, indent=4, ensure_ascii=False)
            with open(self._answer_file, 'w', encoding='utf-8') as f:
                f.write(formatted_data)
            logger.info(f"签到答案 '{answer_text}' (hash: {captcha_img_hash}) 已成功写入本地文件: {self._answer_file}")
        except (FileNotFoundError, IOError, OSError, TypeError) as e: # Added TypeError for non-serializable
            logger.error(f"签到答案写入本地文件失败 ({self._answer_file}): {str(e)}")

    @staticmethod
    def _tohash(img, shape=(10, 10)):
        try:
            if img.mode == 'P': # Palette mode
                img = img.convert('RGBA').convert('RGB') # Convert to RGB via RGBA to handle transparency properly
            elif img.mode == 'RGBA':
                 img = img.convert('RGB') # Convert RGBA to RGB
            elif img.mode != 'RGB' and img.mode != 'L': # Other modes like CMYK, YCbCr
                 img = img.convert('RGB')

            # Now img is either RGB or L (grayscale)
            if img.mode != 'L':
                gray = img.resize(shape, Image.Resampling.LANCZOS).convert('L') # Use LANCZOS for better quality resize
            else:
                gray = img.resize(shape, Image.Resampling.LANCZOS)
        except Exception as e:
            logger.error(f"图像预处理错误 (tohash): {e}")
            return f"error_hashing_preprocess_{str(e)[:20]}"

        s = 0
        hash_str = ''
        if shape[0] * shape[1] == 0: 
            logger.error("Hashing shape has zero dimension.")
            return "error_hashing_shape_zero"
        try:
            # Calculate average pixel value
            pixels = list(gray.getdata())
            if not pixels:
                logger.error("Image has no pixel data after processing.")
                return "error_hashing_no_pixels"
            avg = sum(pixels) / len(pixels)
            
            # Build hash string
            hash_str = ''.join(['1' if pixel > avg else '0' for pixel in pixels])
        except Exception as e:
            logger.error(f"图像像素处理错误 (tohash): {e}")
            return f"error_hashing_pixel_access_{str(e)[:20]}"
        
        if len(hash_str) != shape[0] * shape[1]:
            logger.warning(f"Generated hash length {len(hash_str)} does not match expected {shape[0]*shape[1]}")
        return hash_str

    @staticmethod
    def _comparehash(hash1, hash2, shape=(10, 10)): # shape here is mostly for expected length validation
        n = 0
        expected_len = shape[0] * shape[1]
        if not hash1 or not hash2 or "error_hashing" in hash1 or "error_hashing" in hash2:
            logger.info(f"比较哈希值时发现无效哈希: h1='{hash1}', h2='{hash2}'")
            return 0.0 # Return 0 similarity for error cases instead of -1
        
        if len(hash1) != len(hash2):
            logger.warning(f"比较哈希值时长度不匹配: len(h1)={len(hash1)}, len(h2)={len(hash2)}. Returning 0 similarity.")
            return 0.0
        
        if len(hash1) != expected_len:
            logger.warning(f"哈希值长度 {len(hash1)} 与期望长度 {expected_len} 不符。计算仍将进行，但可能基于非预期哈希。")

        if not hash1: # Avoid division by zero if hash1 (and hash2 due to len check) is empty
            return 0.0

        for i in range(len(hash1)):
            if hash1[i] == hash2[i]:
                n = n + 1
        return n / len(hash1)


    def get_page_source(self, url: str, cookie: str, ua: str, proxy: bool, render: bool) -> str | None:
        # render parameter is not used in this basic implementation
        logger.info(f"获取页面源码: {url} (render={render})") # render is noted but not acted upon
        req_utils = RequestUtils(cookies=cookie, ua=ua, proxies=settings.PROXY if proxy else None)
        res = req_utils.get_res(url)
        
        if res and res.status_code == 200:
            content_type = res.headers.get('content-type', '').lower()
            charset = None
            if 'charset=' in content_type:
                charset = content_type.split('charset=')[-1].split(';')[0].strip()
                logger.info(f"从响应头中检测到编码: {charset}")
                try:
                    return res.content.decode(charset)
                except (UnicodeDecodeError, LookupError) as e:
                    logger.warning(f"使用响应头中的编码 '{charset}' 解码失败: {e}，尝试自动检测或备用编码。")

            # If charset from header failed or not present, try requests' auto-detection first
            if res.encoding and res.encoding.lower() != 'iso-8859-1': # ignore incorrect default by requests for binary
                logger.info(f"尝试使用 requests 检测到的编码: {res.encoding}")
                try:
                    # Accessing res.text forces requests to decode using its detected encoding or fallback
                    return res.text 
                except UnicodeDecodeError as e:
                    logger.warning(f"使用 requests 检测编码 '{res.encoding}' 解码失败: {e}。尝试GBK/UTF-8。")
            
            # Fallback to common encodings for PT sites
            try:
                logger.info("尝试使用 GBK 解码...")
                return res.content.decode('gbk')
            except UnicodeDecodeError:
                logger.info("GBK 解码失败，尝试使用 UTF-8...")
                try:
                    return res.content.decode('utf-8')
                except UnicodeDecodeError as e_utf8:
                    logger.error(f"使用 GBK 和 UTF-8 解码页面源码均失败 {url}: {e_utf8}")
                    logger.error(f"  页面响应内容前100字节 (bytes): {res.content[:100]}")
                    # As a last resort, return requests' text property, which might be garbled.
                    return res.text 
        elif res:
            logger.error(f"获取页面源码失败 {url}. Status: {res.status_code}, Response: {res.text[:200] if hasattr(res, 'text') else 'N/A'}")
        else:
            logger.error(f"获取页面源码失败 {url}. No response from server.")
        return None

    def sign_in_result(self, html_res: str, regexs: list) -> str | None:
        import re # Ensure re is imported
        if not html_res: return None
        for regex_pattern in regexs:
            match = re.search(regex_pattern, html_res, re.IGNORECASE) # Added IGNORECASE just in case
            if match:
                return match.group(0) 
        return None