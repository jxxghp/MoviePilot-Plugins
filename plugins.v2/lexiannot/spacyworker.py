from multiprocessing import Process, Queue
from typing import Dict, List

import spacy
from spacy.tokenizer import Tokenizer

from app.core.cache import cached
from app.log import logger


class SpacyWorker:

    def __init__(self, model='en_core_web_sm'):
        self.task_q = Queue()
        self.result_q = Queue()
        self.status_q = Queue()
        self.model = model

        # 启动子进程
        logger.info(f"正在启动 SpacyWorker 子进程...")
        self.proc = Process(target=self.run, args=(self.model,))
        self.proc.start()

        # 等待子进程返回模型加载状态
        status, info = self.status_q.get()
        if status == 'error':
            self.proc.join()
            raise RuntimeError(f"spaCy 模型加载失败: {info}")
        else:
            logger.info(f"spaCy 模型 `{self.model}` 加载成功")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def run(self, model: str):
        try:
            nlp = SpacyWorker.load_nlp(model)
            infixes = list(nlp.Defaults.infixes)
            infixes = [i for i in infixes if '-' not in i]
            infix_re = spacy.util.compile_infix_regex(infixes)
            nlp.tokenizer = Tokenizer(
                nlp.vocab,
                prefix_search=nlp.tokenizer.prefix_search,
                suffix_search=nlp.tokenizer.suffix_search,
                infix_finditer=infix_re.finditer,
                token_match=nlp.tokenizer.token_match
            )
        except Exception as e:
            self.status_q.put(('error', str(e)))
            return

        # 告诉主进程加载成功
        self.status_q.put(('ok', None))

        while True:
            text = self.task_q.get()
            if text is None:
                break
            doc = nlp(text)
            self.result_q.put([{'text': token.text, 'pos_': token.pos_, 'lemma_': token.lemma_} for token in doc])

    @staticmethod
    @cached(maxsize=1, ttl=3600 * 6)
    def load_nlp(model: str) -> spacy.Language:
        return spacy.load(model)

    def submit(self, text: str) -> List[Dict[str, str]]:
        """
        提交任务并等待结果
        """
        self.task_q.put(text)
        return self.result_q.get()

    def close(self):
        """
        关闭子进程
        """
        if self.proc.is_alive():
            self.task_q.put(None)
            self.proc.join()
            logger.info("SpacyWorker 子进程退出")
